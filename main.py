import io
import logging
from urllib.parse import urlparse

import requests
import trafilatura

from fastapi import FastAPI, Query, HTTPException, Response
from fastapi.responses import JSONResponse

# 配置日志
logging.basicConfig(level=logging.INFO)

# 创建 FastAPI 应用实例
app = FastAPI(
    title="arXiv Single Image Fetcher",
    description="Fetches a single PNG image (x1.png to x4.png) from an arXiv HTML abstract page.",
    version="1.0.0",
)

# 请求超时时间 (秒)
REQUEST_TIMEOUT = 10

@app.get(
    "/get_single_arxiv_image",
    summary="Get a single arXiv image",
    description="Provide an arXiv HTML URL and an image index (1-4) to fetch the corresponding PNG image.",
    responses={
        200: {
            "content": {"image/png": {}},
            "description": "Successfully returned the PNG image.",
        },
        400: {
            "model": dict, # Example structure: {"detail": "Error message"}
            "description": "Invalid input parameters (URL format, missing params, invalid index).",
        },
        404: {
            "model": dict,
            "description": "The requested image index was not found for the given URL.",
        },
        500: {
            "model": dict,
            "description": "Internal server error during image fetching or processing.",
        },
        504: {
            "model": dict,
            "description": "Timeout occurred while fetching the image from arXiv.",
        },
    },
)
async def get_single_arxiv_image(
    # 使用 Query 进行参数校验：必需，描述，别名等
    url: str = Query(
        ...,  # '...' 表示此参数是必需的
        description="The full URL of the arXiv HTML page (e.g., https://arxiv.org/html/2504.07491v1)",
        min_length=15, # 简单的长度校验
        regex=r"^https?://arxiv\.org/html/.*" # 基础的正则表达式校验
    ),
    index: int = Query(
        ...,
        ge=1, # Greater than or equal to 1
        le=4, # Less than or equal to 4
        description="The index of the image to fetch (1, 2, 3, or 4)."
    )
):
    """
    API endpoint to fetch a single PNG image based on arXiv URL and index.
    """
    logging.info(f"Received request for URL: {url}, Index: {index}")

    # --- 基本的 URL 格式再次确认 (虽然 regex 做了部分工作) ---
    try:
        parsed_url = urlparse(url)
        if not (parsed_url.scheme in ['http', 'https'] and parsed_url.netloc == 'arxiv.org' and parsed_url.path.startswith('/html/')):
             # 可选：如果需要更严格的校验，可以在这里抛出异常
             logging.warning(f"URL '{url}' passed regex but failed detailed parse check. Proceeding cautiously.")
             # raise HTTPException(status_code=400, detail="Invalid arXiv HTML URL format.")
    except ValueError:
        logging.error(f"Could not parse URL: {url}")
        raise HTTPException(status_code=400, detail="Invalid URL format.")

    # --- 构造图片 URL ---
    base_url = url.rstrip('/')
    image_filename = f"x{index}.png"
    image_url = f"{base_url}/{image_filename}"

    logging.info(f"Attempting to fetch image: {image_url}")

    # --- 发起 HTTP 请求获取图片 ---
    try:
        # 注意：requests 是同步库。FastAPI 会在线程池中运行它，对于 I/O 密集型任务，
        # 更好的选择是使用异步库如 httpx。但对于简单场景，requests 也可以工作。
        response = requests.get(image_url, timeout=REQUEST_TIMEOUT, stream=False)

        # --- 处理响应 ---
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '').lower()
            if 'image/png' in content_type:
                logging.info(f"Successfully fetched {image_filename}. Content-Type: {content_type}")
                # 使用 FastAPI 的 Response 类直接返回二进制内容和正确的 MIME 类型
                return Response(content=response.content, media_type="image/png")
            else:
                logging.warning(f"URL {image_url} returned 200 OK but Content-Type is '{content_type}', not 'image/png'.")
                # 返回 400 还是 500 取决于你如何定义错误，这里认为是客户端请求了一个非图片资源（即使URL是对的）
                raise HTTPException(
                    status_code=400, # Bad Request - resource found but not the expected type
                    detail=f"Resource found at index {index}, but it's not a PNG image (Content-Type: {content_type})."
                )

        elif response.status_code == 404:
            logging.info(f"Image {image_filename} not found (404) at {image_url}.")
            raise HTTPException(status_code=404, detail=f"Image index {index} not found for this URL.")

        else:
            # 处理其他 HTTP 错误状态码
            logging.warning(f"Failed to fetch {image_filename}. Status code: {response.status_code}. URL: {image_url}")
            raise HTTPException(
                status_code=502, # Bad Gateway - indicate upstream server error
                detail=f"Failed to fetch image from arXiv. Status code: {response.status_code}"
            )

    except requests.exceptions.Timeout:
        logging.error(f"Timeout occurred while fetching {image_url}")
        raise HTTPException(status_code=504, detail="Gateway Timeout while fetching image from arXiv.")
    except requests.exceptions.ConnectionError as e:
         logging.error(f"Connection error while fetching {image_url}: {e}")
         raise HTTPException(status_code=503, detail=f"Service Unavailable. Could not connect to arXiv server to fetch image.")
    except requests.exceptions.RequestException as e:
        # 捕获其他 requests 可能抛出的异常
        logging.error(f"An unexpected error occurred fetching {image_url}: {e}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")

# --- 运行 FastAPI 应用 ---
# --- 新增：文章内容提取端点 ---
@app.get(
    "/extract_article_content",
    summary="Extract Main Content from URL",
    description="Fetches the content of a given URL and attempts to extract the main article text, removing boilerplate.",
    responses={
        200: {
            "content": {"application/json": {"example": {"url": "http://example.com/article", "content": "This is the main article content..."}}},
            "description": "Successfully extracted the article content.",
        },
        400: {
            "model": dict,
            "description": "Invalid input URL.",
        },
        404: {
            "model": dict,
            "description": "The target URL was not found (404).",
        },
        422: {
             "model": dict,
             "description": "Could not extract main content from the fetched page (e.g., not an article page, or extraction failed).",
        },
        500: {
            "model": dict,
            "description": "Internal server error during fetching or extraction.",
        },
        502: {
            "model": dict,
            "description": "Bad Gateway: Error communicating with the target URL server (non-404 error).",
        },
        503: {
             "model": dict,
             "description": "Service Unavailable: Could not connect to the target URL server.",
        },
        504: {
            "model": dict,
            "description": "Gateway Timeout: Timeout occurred while fetching the content from the target URL.",
        },
    },
)
async def extract_article_content(
    url: str = Query(
        ...,
        description="The full URL of the article page to process.",
        min_length=10, # 简单的长度校验
    )
):
    """
    API endpoint to fetch HTML from a URL and extract main article content using Trafilatura.
    """
    logging.info(f"Received request to extract content from URL: {url}")

    # --- 基础 URL 校验 ---
    try:
        parsed_url = urlparse(url)
        if not (parsed_url.scheme in ['http', 'https'] and parsed_url.netloc):
            raise ValueError("Invalid URL scheme or netloc")
    except ValueError:
        logging.error(f"Invalid URL format provided: {url}")
        raise HTTPException(status_code=400, detail="Invalid URL format. Please provide a full URL (e.g., http://example.com).")

    # --- 发起 HTTP 请求获取 HTML 页面 ---
    headers = {
        # 伪装成浏览器，提高成功率
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    html_content: str | None = None
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, stream=False, allow_redirects=True) # 允许重定向

        if response.status_code == 200:
            # 检查内容类型，如果不是HTML，可能无法提取
            content_type = response.headers.get('Content-Type', '').lower()
            if 'html' not in content_type:
                 logging.warning(f"URL {url} returned non-HTML content-type: {content_type}. Extraction might fail.")
                 # 你可以选择在这里直接报错，或者尝试提取
                 # raise HTTPException(status_code=415, detail=f"Unsupported Media Type: Expected HTML, got {content_type}")

            # 尝试获取文本内容，requests 会尝试猜测编码
            html_content = response.text
            logging.info(f"Successfully fetched HTML from {url} (status {response.status_code})")

        elif response.status_code == 404:
            logging.info(f"Target URL not found (404): {url}")
            raise HTTPException(status_code=404, detail="The target article URL was not found.")
        else:
            # 其他客户端或服务器错误
            logging.warning(f"Failed to fetch content from {url}. Status code: {response.status_code}")
            raise HTTPException(
                status_code=502, # Bad Gateway - 表示我们作为代理/网关无法从上游获取有效响应
                detail=f"Failed to fetch content from the target URL. Status code: {response.status_code}"
            )

    except requests.exceptions.Timeout:
        logging.error(f"Timeout occurred while fetching {url}")
        raise HTTPException(status_code=504, detail="Gateway Timeout while fetching content from the target URL.")
    except requests.exceptions.ConnectionError as e:
         logging.error(f"Connection error while fetching {url}: {e}")
         raise HTTPException(status_code=503, detail=f"Service Unavailable. Could not connect to the target URL server.")
    except requests.exceptions.RequestException as e:
        # 捕获其他 requests 可能抛出的异常 (如 TooManyRedirects)
        logging.error(f"An unexpected error occurred fetching {url}: {e}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred while fetching the URL: {e}")

    # --- 如果成功获取 HTML，则尝试提取内容 ---
    if html_content:
        try:
            # 使用 trafilatura 提取主要内容，输出为纯文本
            # include_comments=False: 不包含评论
            # include_tables=True: 可以选择是否包含表格内容
            extracted_text = trafilatura.extract(
                html_content,
                include_comments=False,
                output_format='txt',
                include_tables=False # 通常文章主体不需要表格，根据需要调整
            )

            if extracted_text:
                logging.info(f"Successfully extracted content for {url}. Length: {len(extracted_text)} chars.")
                return JSONResponse(content={
                    "url": url,
                    "content": extracted_text
                })
            else:
                # 获取到页面但无法提取主体内容
                logging.warning(f"Could not extract main content from {url}, possibly not an article page or extraction failed.")
                raise HTTPException(
                    status_code=422, # Unprocessable Entity - 服务器理解请求，但无法处理内容
                    detail="Could not extract main content from the provided URL. It might not be a standard article page."
                )

        except Exception as e:
            # 捕获 trafilatura 可能出现的意外错误
            logging.error(f"Error during content extraction for {url}: {e}", exc_info=True) # 记录堆栈跟踪
            raise HTTPException(status_code=500, detail=f"An internal error occurred during content extraction: {e}")
    else:
         # 理论上如果上面获取html的逻辑没问题，这里不会执行，但作为保险
         logging.error(f"Reached content extraction step but html_content is None for {url}.")
         raise HTTPException(status_code=500, detail="Internal error: HTML content was unexpectedly missing.")

if __name__ == "__main__":
    import uvicorn
    # host="0.0.0.0" 让服务可以被局域网访问
    # reload=True 会在代码变动时自动重启服务，适合开发环境
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)