from fastapi import Path, Cookie, Body, status
from fastapi.responses import Response
from functools import lru_cache
from typing import Annotated
from datetime import datetime
import httpx
import json

from common import settings
from common.settings import get_settings, TOKEN_LIFE
from common.schemas import ResponseCookies, HttpxRequest, create_response
from app.services.api_v1 import lp_service


cookies = Annotated[ResponseCookies | None, Cookie()]
cookie = Annotated[str | None, Cookie()]
go_resp = Annotated[tuple[dict,int,str] | tuple[str,int,str] | None | Response, "Parametro Necesario"]
edutrace_user_rep = Annotated[Response | dict | str | None, "Parametro Necesario"]
req_body = Annotated[dict | None, Body()]
id = Annotated[int | str, Path()]

TIMEOUT = 10


class InternalService:
    def __init__(self):
        self.settings = get_settings()
        self.lp_service = lp_service.get_service(1.64)
        self.go_client = httpx.Client(verify=self.settings.ca_file)
        self.go_internal_url = f"{self.settings.go_base_url}/internal/v1"
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


    def go_requests(self, req: str, req_data: HttpxRequest) -> go_resp:
        response = httpx.Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)

        try:
            match req:
                case "put":
                    if req_data.json is not None:
                        response = self.go_client.put(
                            url=req_data.url,
                            headers=self.headers,
                            json=req_data.json,
                        )
                case "post":
                    if req_data.json is not None:
                        response = self.go_client.post(
                            url=req_data.url,
                            headers=self.headers,
                            json=req_data.json,
                        )
        except httpx.ConnectError as e:
            response_data = {
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "content": "Go - EduTrace no responde. " + str(e),
                "cookies": None
            }

            return create_response(response_data)

        if "application/json" in response.headers.get("content-type", ""):
            return response.json(), response.status_code, datetime.now().isoformat()
        elif "text/plain" in response.headers.get("content-type", ""):
            return response.text, response.status_code, datetime.now().isoformat()
        else:
            return None


    def edutrace_user(self, access_token: str) -> edutrace_user_rep:
        go_user = self.obtain_user_id(access_token)

        if isinstance(go_user, Response): #error
            return go_user
        else:
            user_external_id = go_user["content"]["external_id"]

            go_user_courses = self.obtain_user_courses(access_token, user_external_id)

            if isinstance(go_user_courses, Response):  # error
                return go_user_courses
            else:
                d2l_body = go_user_courses["content"]["d2l_response"]
                # debe mandar una peticion de /dropbox/folders por cada orgunit del d2l_body
                #self.put_assigment(d2l_body)

                ticket_rep = self.create_ticket(user_external_id)

                if ticket_rep.status_code not in (418, 400, 404, 422, 503):
                    ticket = json.loads(ticket_rep.body).get("ticket")

                    return ticket
                else:
                    return ticket_rep # error


    def obtain_user_id(self, access_token: str) -> edutrace_user_rep:
        d2l_response = self.lp_service.whoami(access_token)

        if d2l_response.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
            body_type = d2l_response.media_type

            match body_type:
                case "application/json":
                    d2l_response_body = json.loads(d2l_response.body)

                    go_resp = self.put_user(d2l_response_body)
                    go_rep_status = go_resp.status_code

                    response_data = {"status_code": go_rep_status,"content": {},"cookies": None}

                    match go_rep_status:
                        case status.HTTP_200_OK | status.HTTP_201_CREATED:
                            go_rep_body = json.loads(go_resp.body)

                            response_data["content"] = go_rep_body

                            return response_data
                        case _:
                            if go_resp.media_type == "text/plain":
                                response_data["content"] = {"exception": go_resp.body.decode("utf-8")}
                            elif go_resp.media_type == "application/json":
                                response_data["content"] = {
                                    "error": json.loads(go_resp.body).get("error"),
                                    "code": json.loads(go_resp.body).get("code"),
                                }
                            else:
                                response_data["content"] = {"error": go_resp.body.decode("utf-8")}

                            return create_response(response_data)
                case _:
                    response_data = {
                        "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
                        "content": "El cuerpo de la respuesta no es valido",
                        "cookies": None
                    }

                    return create_response(response_data)
        else:
            return d2l_response


    def obtain_user_courses(self, access_token: str, external_id: str) -> edutrace_user_rep:
        d2l_response = self.lp_service.myenrollments(access_token)

        if d2l_response.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
            body_type = d2l_response.media_type

            match body_type:
                case "application/json":
                    d2l_response_body = json.loads(d2l_response.body)

                    go_resp = self.put_enrollments(d2l_response_body, external_id)
                    go_rep_status = go_resp.status_code

                    response_data = {"status_code": go_rep_status,"content": {},"cookies": None}

                    match go_rep_status:
                        case status.HTTP_200_OK:
                            go_rep_body = json.loads(go_resp.body)

                            response_data["content"] = {
                                "d2l_response": d2l_response_body,
                                "go_response": go_rep_body
                            }

                            return response_data
                        case _:
                            if go_resp.media_type == "text/plain":
                                response_data["content"] = {"exception": go_resp.body.decode("utf-8")}
                            elif go_resp.media_type == "application/json":
                                response_data["content"] = {
                                    "error": json.loads(go_resp.body).get("error"),
                                    "code": json.loads(go_resp.body).get("code"),
                                }
                            else:
                                response_data["content"] = {"error": go_resp.body.decode("utf-8")}

                            return create_response(response_data)
                case _:
                    response_data = {
                        "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
                        "content": "El cuerpo de la respuesta no es valido",
                        "cookies": None
                    }

                    return create_response(response_data)
        else:
            return d2l_response


    def put_user(self, body: req_body, external_id: id | None = None) -> Response:
        if body is not None:
            user_id = external_id if external_id is not None else body.get("Identifier")

            user_data = {
                "Identifier": user_id,
                "FirstName": body["FirstName"],
                "LastName": body["LastName"],
                "UniqueName": body["UniqueName"] + "@example.com",
                "email": body["UniqueName"] + "@example.com"
            }

            url = f"{self.go_internal_url}/users/{user_id}"
            go_req_data = HttpxRequest(url=url, json=user_data)

            go_resp = self.go_requests(req="put", req_data=go_req_data)

            if isinstance(go_resp, Response):  # error response
                return go_resp

            if go_resp is not None:
                json_response, resp_status, response_time = go_resp

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
                    "status_code": status.HTTP_418_IM_A_TEAPOT,
                    "content": "La peticion a EduTrace fallo",
                    "cookies": None
                }

                return create_response(response_data)
        else:
            response_data = {
                "status_code": status.HTTP_418_IM_A_TEAPOT,
                "content": "La peticion a Brightspace fallo",
                "cookies": None
            }

            return create_response(response_data)


    def put_enrollments(self, body: req_body, external_id: id) -> Response:
        if body is not None:
            url = f"{self.go_internal_url}/users/{external_id}/enrollments"
            go_req_data = HttpxRequest(url=url, json=body)

            go_resp = self.go_requests(req="put", req_data=go_req_data)

            if isinstance(go_resp, Response): #error response
                return go_resp

            if go_resp is not None:
                json_response, resp_status, response_time = go_resp

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
                    "status_code": status.HTTP_418_IM_A_TEAPOT,
                    "content": "La peticion a EduTrace fallo",
                    "cookies": None
                }

                return create_response(response_data)
        else:
            response_data = {
                "status_code": status.HTTP_418_IM_A_TEAPOT,
                "content": "La peticion a Brightspace fallo",
                "cookies": None
            }

            return create_response(response_data)


    def put_assigment(self, course_external_id: id, body: req_body) -> Response:
        return


    def create_ticket(self, external_id: str) -> Response:
        ticket_req = {
            "user_external_id": external_id
        }

        url = f"{self.go_internal_url}/session-tickets"
        go_req_data = HttpxRequest(url=url, json=ticket_req)

        go_resp = self.go_requests(req="post", req_data=go_req_data)

        if isinstance(go_resp, Response):  # error response
            return go_resp

        if go_resp is not None:
            json_response, resp_status, response_time = go_resp

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
                "status_code": status.HTTP_418_IM_A_TEAPOT,
                "content": "La peticion a EduTrace fallo",
                "cookies": None
            }

            return create_response(response_data)


@lru_cache()
def get_service() -> InternalService:
    return InternalService()