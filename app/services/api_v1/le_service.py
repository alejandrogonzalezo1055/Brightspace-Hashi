from fastapi import Cookie, status
from functools import lru_cache
from typing import Annotated
import httpx

from common.settings import get_settings
from common.schemas import ResponseCookies, ProductVersion, create_response


cookies = Annotated[ResponseCookies | None, Cookie()]
cookie = Annotated[str | None, Cookie()]
httpx_resp = Annotated[tuple[dict,int] | tuple[str,int] | None, "Parametro Necesario"]


class LEService():
    def __init__(self, product_version: ProductVersion):
        self.le_version = product_version
        self.settings = get_settings()
        self.httpx_client = httpx.Client()
        self.url = f"{self.settings.get_api_url(1)}/le/{self.le_version}"


    def httpx_requests(self, req: str, url: str, access_token: cookie) -> httpx_resp:
        response = httpx.Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)

        match req:
            case "get":
                response = self.httpx_client.get(
                    url=url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )

        if response.is_success and "application/json" in response.headers.get("content-type", ""):
            return response.json(), response.status_code
        elif response.is_success and "text/plain" in response.headers.get("content-type", ""):
            return response.text, response.status_code
        else:
            return None


@lru_cache()
def get_service(product_version: ProductVersion) -> LEService:
    return LEService(product_version)