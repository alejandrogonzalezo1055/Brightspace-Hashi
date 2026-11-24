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
from common.errors import get_logger
from app.services.api_v1 import lp_service, le_service


cookies = Annotated[ResponseCookies | None, Cookie()]
cookie = Annotated[str | None, Cookie()]
go_resp = Annotated[tuple[dict,int,str] | tuple[str,int,str] | tuple[bytes,int,str] | None | Response, "Parametro Necesario"]
edutrace_user_rep = Annotated[Response | dict | str | None, "Parametro Necesario"]
req_body = Annotated[dict | None, Body()]
id = Annotated[int | str, Path()]


class InternalService:
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger().logger
        self.lp_service = lp_service.get_service("1.64")
        self.le_service = le_service.get_service("1.100")
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


    def go_requests(self, req: str, req_data: HttpxRequest, file: bool = False) -> go_resp:
        response = httpx.Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)

        try:
            match req:
                case "put":
                    if req_data.req_content is not None and not file:
                        response = self.go_client.put(
                            url=req_data.url,
                            headers=self.headers,
                            json=req_data.req_content,
                        )
                    elif req_data.req_content is not None:
                        response = self.go_client.put(
                            url=req_data.url,
                            headers=self.headers,
                            content=req_data.req_content,
                        )
                case "post":
                    if req_data.req_content is not None:
                        response = self.go_client.post(
                            url=req_data.url,
                            headers=self.headers,
                            json=req_data.req_content,
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

        elif response.is_success and response.headers.get("content-type", "").startswith(("text/plain", "d2l/unknowntype")):
            return response.text, response.status_code, datetime.now().isoformat()

        elif response.is_success and "application/pdf" in response.headers.get("content-type", ""):
            return response.content, response.status_code, datetime.now().isoformat()

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

                d2l_orgs = d2l_body["Items"]
                for d2l_org in d2l_orgs:
                    if d2l_org["OrgUnit"]["Type"]["Id"] == 3:
                        go_assigments = self.obtain_user_assigments(access_token, d2l_org["OrgUnit"]["Id"])

                        if isinstance(go_assigments, Response):
                            return go_assigments
                        else:
                            folder = go_assigments["content"]["files_needed"]

                            for file in folder:
                                folder_id = file["folder"]
                                file_id = file["file_id"]
                                name = file["name"]

                                self.obtain_assigments_files(access_token, orgUnitId=d2l_org["OrgUnit"]["Id"],
                                                             folderId=folder_id, fileId=file_id, name=name)


                ticket_rep = self.create_ticket(user_external_id)

                if ticket_rep.status_code not in (418, 400, 404, 422, 503):
                    ticket = json.loads(ticket_rep.body).get("ticket")

                    return ticket
                else:
                    return ticket_rep # error


    def obtain_user_id(self, access_token: str) -> edutrace_user_rep:
        d2l_response = self.lp_service.whoami(access_token)

        if d2l_response.status_code not in (503, 401, 403, 501):
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

        if d2l_response.status_code not in (503, 401, 403, 501):
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


    def obtain_user_assigments(self, access_token: str, orgUnitId: int):
        d2l_response = self.le_service.dropbox_folders(access_token=access_token, orgUnitId=orgUnitId)

        if d2l_response.status_code not in (503, 401, 403, 501):
            body_type = d2l_response.media_type

            match body_type:
                case "application/json":
                    d2l_response_body = json.loads(d2l_response.body)

                    go_resp = self.put_assigment(external_id=f"d2l:ou:{orgUnitId}",body=d2l_response_body)
                    go_rep_status = go_resp.status_code

                    response_data = {"status_code": go_rep_status, "content": {}, "cookies": None}

                    match go_rep_status:
                        case status.HTTP_200_OK:
                            go_rep_body = json.loads(go_resp.body)

                            response_data["content"] = go_rep_body

                            self.logger.info(f"Obtain User Assigments. Go acepto y registro la organizacion: '{orgUnitId}'")

                            return response_data
                        case _:
                            self.logger.error(f"Obtain User Assigments."
                                              f"Go no acepto la organizacion: '{orgUnitId}', devolvio el codigo: '{go_rep_status}'")
                case _:
                    response_data = {
                        "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
                        "content": "El cuerpo de la respuesta no es valido",
                        "cookies": None
                    }

                    return create_response(response_data)
        else:
            return d2l_response


    def obtain_assigments_files(self, access_token: str, orgUnitId: int, folderId: str, fileId: int, name: str):
        d2l_response = self.le_service.get_archivo(access_token=access_token,orgUnitId=orgUnitId,
                                                   folderId=int(folderId.removeprefix("d2l:folder:")),fileId=fileId)

        if d2l_response.status_code not in (503, 401, 403, 501):
            d2l_response_body = d2l_response.body

            go_resp = self.put_assigment_file(body=d2l_response_body, external_id=f"d2l:ou:{orgUnitId}"
                                              , folderId=folderId, fileId=fileId
                                              , name=name)
            go_rep_status = go_resp.status_code

            response_data = {"status_code": go_rep_status, "content": {}, "cookies": None}

            match go_rep_status:
                case status.HTTP_200_OK:
                    go_rep_body = go_resp.body

                    response_data["content"] = go_rep_body

                    self.logger.info(f"Obtain Assigments Files. Go obtuvo el archivo: '{fileId}'"
                                     f", del folder: '{folderId}', y organizacion: '{orgUnitId}'")

                    return response_data
                case _:
                    self.logger.error(f"Obtain Assigments Files."
                                      f"Go no acepto el archivo: '{orgUnitId}'"
                                      f", devolvio el codigo: '{go_rep_status}'")
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
            go_req_data = HttpxRequest(url=url, req_content=user_data)

            go_resp = self.go_requests(req="put", req_data=go_req_data)

            if isinstance(go_resp, Response):  # error response
                return go_resp

            if go_resp is not None and isinstance(go_resp, tuple):
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
            go_req_data = HttpxRequest(url=url, req_content=body)

            go_resp = self.go_requests(req="put", req_data=go_req_data)

            if isinstance(go_resp, Response): #error response
                return go_resp

            if go_resp is not None and isinstance(go_resp, tuple):
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


    def put_assigment(self, body: req_body, external_id: id) -> Response:
        if body is not None:
            url = f"{self.go_internal_url}/courses/{external_id}/assignments"
            go_req_data = HttpxRequest(url=url, req_content=body)

            go_resp = self.go_requests(req="put", req_data=go_req_data)

            if isinstance(go_resp, Response):  # error response
                return go_resp

            if go_resp is not None and isinstance(go_resp, tuple):
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


    def put_assigment_file(self, body: req_body, external_id: id, folderId: id, fileId: id, name: str) -> Response:
        if body is not None:
            url = f"{self.go_internal_url}/courses/{external_id}/assignments/{folderId}/files/{fileId}?name={name}"
            go_req_data = HttpxRequest(url=url, req_content=body)

            go_resp = self.go_requests(req="put", req_data=go_req_data, file=True)

            if isinstance(go_resp, Response):  # error response
                return go_resp

            if go_resp is not None and isinstance(go_resp, tuple):
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


    def create_ticket(self, external_id: str) -> Response:
        ticket_req = {
            "user_external_id": external_id
        }

        url = f"{self.go_internal_url}/session-tickets"
        go_req_data = HttpxRequest(url=url, req_content=ticket_req)

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