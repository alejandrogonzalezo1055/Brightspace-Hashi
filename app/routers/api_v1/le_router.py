from fastapi import APIRouter, Depends, Cookie, Response, Path
from typing import Annotated

from app.services.api_v1.le_service import LEService, get_service
from common.schemas import ResponseCookies, ProductVersionValidator


router = APIRouter(prefix="/le/{product_version}", dependencies=[Depends(ProductVersionValidator("le"))], tags=["Learning Enviroment"])


LPService = Annotated[LEService, Depends(get_service)]

cookies = Annotated[ResponseCookies | None, Cookie()]
cookie = Annotated[str | None, Cookie()]
id = Annotated[int, Path()]


@router.get("/{orgUnitId}/dropbox/folders/")
def dropbox_folders(service: LPService, access_token: cookie, orgUnitId: id) -> Response:
    return service.dropbox_folders(access_token, orgUnitId)

@router.get("/{orgUnitId}/dropbox/folders/{folderId}/attachments/{fileId}")
def descargar_archivo(service: LPService, access_token: cookie, orgUnitId: id, folderId: id, fileId: id) -> Response:
    return service.get_archivo(access_token, orgUnitId, folderId, fileId)