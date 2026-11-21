from fastapi import Cookie, Response, Path, status
from functools import lru_cache
from typing import Annotated
from datetime import datetime
import httpx

from common.settings import get_settings, TOKEN_LIFE
from common.schemas import ResponseCookies, ProductVersion, create_response


cookies = Annotated[ResponseCookies | None, Cookie()]
cookie = Annotated[str | None, Cookie()]
httpx_resp = Annotated[tuple[dict,int,str] | tuple[str,int,str] | Response | None, "Parametro Necesario"]


class LEService():
    def __init__(self, product_version: ProductVersion):
        self.le_version = product_version
        self.settings = get_settings()
        self.httpx_client = httpx.Client()
        self.url = f"{self.settings.get_api_url(1)}/le/{self.le_version}"


    def httpx_requests(self, req: str, url: str, access_token: cookie) -> httpx_resp:
        response = httpx.Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)

        try:
            match req:
                case "get":
                    response = self.httpx_client.get(
                        url=url,
                        headers={"Authorization": f"Bearer {access_token}"}
                    )
        except httpx.ConnectError as e:
            response_data = {
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "content": str(e),
                "cookies": None
            }

            return create_response(response_data)

        if response.is_success and "application/json" in response.headers.get("content-type", ""):
            return response.json(), response.status_code, datetime.now().isoformat()
        elif response.status_code in (401, 403):
            response_data = {
                "status_code": response.status_code,
                "content": response.text,
                "cookies": None
            }

            return create_response(response_data)
        else:
            return None


    def dropbox_folders(self, access_token: cookie, orgUnitId: int) -> Response:
        url = f"{self.url}/{orgUnitId}/dropbox/folders/"
        response = self.httpx_requests(req="get", url=url, access_token=access_token)

        if response is not None and isinstance(response, tuple):
            json_response, resp_status, response_time = response
            response_data = {
                "status_code": resp_status,
                "content": json_response,
                "cookies": [
                    {
                        "key": "response_time",
                        "value": response_time,
                        "httponly": True,
                        "samesite": "lax",
                        "max_age": TOKEN_LIFE
                    }
                ]
            }

            return create_response(response_data)
        elif isinstance(response, Response):
            return response
        else:
            response_data = {
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "content": "La respuesta de Brightspace fue 'None'",
                "cookies": None
            }

            return create_response(response_data)


@lru_cache()
def get_service(product_version: ProductVersion) -> LEService:
    return LEService(product_version)