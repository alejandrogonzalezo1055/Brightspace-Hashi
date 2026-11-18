from fastapi import Path, Cookie, Body, status
from fastapi.responses import Response
from functools import lru_cache
from typing import Annotated
import httpx
import json

from common import settings
from common.settings import get_settings
from common.schemas import ResponseCookies, HttpxRequest, create_response
from app.services.api_v1 import lp_service


cookies = Annotated[ResponseCookies | None, Cookie()]
cookie = Annotated[str | None, Cookie()]
httpx_resp = Annotated[tuple[dict,int] | tuple[str,int] | None, "Parametro Necesario"]
req_body = Annotated[dict | str, Body()]
id = Annotated[int, Path()]

TIMEOUT = 10


class InternalService():
    def __init__(self):
        self.settings = get_settings()
        self.lp_service = lp_service.get_service(1.64)
        self.httpx_client = httpx.Client()
        self.base_url = self.settings.go_base_url
        self.ca_file = self.settings.ca_file
        self.headers = {"Authorization": f"Bearer {self.settings.internal_api_key.get_secret_value()}"}


    def health(self) -> Response:
        response_data = {
            "status_code": status.HTTP_200_OK,
            "content": {
                "status": "ok",
                "brightspace": settings.brightspace_call
            },
            "cookies": None
        }

        return create_response(response_data)


    def httpx_requests(self, req: str, req_data: HttpxRequest, access_token: cookie = None) -> httpx_resp:
        response = httpx.Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)

        match req:
            case "post":
                if req_data.json is not None:
                    response = self.httpx_client.post(
                        url=req_data.url,
                        headers=self.headers,
                        json=req_data.json
                    )
                elif req_data.text is not None:
                    response = self.httpx_client.post(
                        url=req_data.url,
                        headers=self.headers,
                        content=req_data.text
                    )

        if response.is_success and "application/json" in response.headers.get("content-type", ""):
            return response.json(), response.status_code
        else:
            return response.text, response.status_code


    def edutrace_user(self, access_token: str):
        whoami_response = self.lp_service.whoami(access_token)

        if "application/json" in whoami_response.media_type:
            response_body = json.loads(whoami_response.body)
        elif "text/plain" in whoami_response.media_type:
            response_body = whoami_response.body.decode("utf-8")
        else:
            response_body = "Fallo"

        self.put_user(response_body)

        myenrollments_response = self.lp_service.myenrollments(access_token)

        return


    def put_user(self, body: req_body, external_id: id | None = None) -> Response:
        if type(body) is dict:
            user_id = external_id if external_id else body.get("Identifier")

            user_data = {
                "Identifier": user_id,
                "FirstName": body["FirstName"],
                "LastName": body["LastName"],
                "UniqueName": body["UniqueName"] + "@example.com",
                "email": body["UniqueName"] + "@example.com"
            }

            response_data = {}

            return create_response(response_data)
        else:
            response_data = {
                "status_code": status.HTTP_418_IM_A_TEAPOT,
                "content": "",
                "cookies": None
            }

            return create_response(response_data)


    def put_enrollments(self, external_id: id, body: req_body) -> Response:
        return


    def put_assigment(self, course_external_id: id, body: req_body) -> Response:
        return


    def create_ticket(self, external_id) -> Response:
        return


@lru_cache()
def get_service() -> InternalService:
    return InternalService()