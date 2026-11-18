from fastapi import Cookie, Path, status
from fastapi.responses import Response
from functools import lru_cache
from typing import Annotated
import httpx

from common.settings import get_settings
from common.schemas import ResponseCookies, ProductVersion, create_response


cookies = Annotated[ResponseCookies | None, Cookie()]
cookie = Annotated[str | None, Cookie()]
httpx_resp = Annotated[tuple[dict,int] | tuple[str,int] | None, "Parametro Necesario"]
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
            return response.json(), response.status_code
        elif response.is_success and "text/plain" in response.headers.get("content-type", ""):
            return response.text, response.status_code
        else:
            return None


    def whoami(self, access_token: cookie) -> Response:
        url = f"{self.url}/users/whoami"
        json_or_txt_response, resp_status = self.httpx_requests(req="get", url=url, access_token=access_token)

        response_data = {
            "status_code": resp_status,
            "content": json_or_txt_response,
            "cookies": None
        }

        return create_response(response_data)


    # NO TENGO PERMISOS
    def my_profile(self, ProfileIdentifier: profile_id, access_token: cookie) -> Response:
        url = f"{self.url}/profile/{ProfileIdentifier}"
        json_response, resp_status = self.httpx_requests(req="get", url=url, access_token=access_token)

        response_data = {
            "status_code": resp_status,
            "content": json_response,
            "cookies": None
        }

        return create_response(response_data)


    def myenrollments(self, access_token: cookie) -> Response:
        url = f"{self.url}/enrollments/myenrollments/"
        json_response, resp_status = self.httpx_requests(req="get", url=url, access_token=access_token)

        response_data = {
            "status_code": resp_status,
            "content": json_response,
            "cookies": None
        }

        return create_response(response_data)


@lru_cache()
def get_service(product_version: float) -> LPService:
    return LPService(product_version)