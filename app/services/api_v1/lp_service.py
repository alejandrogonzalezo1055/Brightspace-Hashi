from fastapi import Cookie, Path, status
from fastapi.responses import Response
from functools import lru_cache
from itertools import chain
from typing import Annotated
from datetime import datetime
import httpx

from common.settings import get_settings, TOKEN_LIFE
from common.schemas import ResponseCookies, ProductVersion, create_response


cookies = Annotated[ResponseCookies | None, Cookie()]
cookie = Annotated[str | None, Cookie()]
httpx_resp = Annotated[tuple[dict,int,str] | tuple[str,int,str] | None, "Parametro Necesario"]
profile_id = Annotated[str, Path()]


class LPService:
    def __init__(self, product_version: ProductVersion):
        self.lp_version = product_version
        self.settings = get_settings()
        self.httpx_client = httpx.Client()
        self.url = f"{self.settings.get_api_url(1)}/lp/{self.lp_version}"


    def httpx_requests(self, req: str, url: str, access_token: cookie) -> httpx_resp:
        response = httpx.Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)

        match req:
            case "get":
                response = self.httpx_client.get(
                    url=url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )

        if response.is_success and "application/json" in response.headers.get("content-type", ""):
            return response.json(), response.status_code, datetime.now().isoformat()
        else:
            return None


    def whoami(self, access_token: cookie) -> Response:
        url = f"{self.url}/users/whoami"
        response = self.httpx_requests(req="get", url=url, access_token=access_token)

        if response is not None:
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
        else:
            response_data = {
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "content": "La respuesta de Brightspace fue 'None'",
                "cookies": None
            }

            return create_response(response_data)


    def myenrollments(self, access_token: cookie, bookmark: str | None = None, paginas: list | None = None) -> Response:
        if bookmark is None:
            url = f"{self.url}/enrollments/myenrollments/"
            paginas = []
        else:
            url = f"{self.url}/enrollments/myenrollments/?bookmark={bookmark}"

        response = self.httpx_requests(req="get", url=url, access_token=access_token)

        if response is not None:
            json_response, resp_status, response_time = response

            more_pages = json_response["PagingInfo"]["HasMoreItems"]
            bookmark = json_response["PagingInfo"]["Bookmark"]

            paginas.append(json_response["Items"])

            if more_pages:
                self.myenrollments(access_token=access_token, bookmark=bookmark, paginas=paginas)

            flat_pages = list(chain.from_iterable(paginas))

            response_data = {
                "status_code": resp_status,
                "content": {"Items": flat_pages},
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
        else:
            response_data = {
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "content": "La respuesta de Brightspace fue 'None'",
                "cookies": None
            }

            return create_response(response_data)


@lru_cache()
def get_service(product_version: float) -> LPService:
    return LPService(product_version)