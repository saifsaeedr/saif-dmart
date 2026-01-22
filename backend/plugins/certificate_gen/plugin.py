import io
import os
from utils.internal_error_code import InternalErrorCode
from models.enums import QueryType
import models.api as api
import models.core as core
from data_adapters.adapter import data_adapter as db
import utils.regex as regex
from fastapi import APIRouter, Path, Depends, status
from starlette.responses import StreamingResponse
from utils.jwt import JWTBearer

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader, PdfWriter

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
import arabic_reshaper
from bidi.algorithm import get_display


router = APIRouter()


def get_positioning_config(request_type):
    positioning_configs = {
        "3ashat_idak": {
            "orientation": "portrait",
            "display_name": {
                "x": 300,
                "y": 600,
                "font_size": 48
            },
            "signatures": {
                "x_center": 300,
                "y_position": 90,
                "name_y": 65,
                "title_y": 50,
                "signature_width": 120,
                "signature_height": 60,
                "name_font_size": 20,
                "title_font_size": 16
            }
        },
        "alzain_male": {
            "orientation": "landscape",
            "display_name": {
                "x": 425,
                "y": 380,
                "font_size": 24
            },
            "signatures": {
                "x_center": 400,
                "y_position": 120,
                "name_y": 95,
                "title_y": 80,
                "signature_width": 100,
                "signature_height": 50,
                "name_font_size": 18,
                "title_font_size": 14
            }
        },
        "alzain_female": {
            "orientation": "landscape",
            "display_name": {
                "x": 425,
                "y": 380,
                "font_size": 24
            },
            "signatures": {
                "x_center": 400,
                "y_position": 120,
                "name_y": 95,
                "title_y": 80,
                "signature_width": 100,
                "signature_height": 50,
                "name_font_size": 18,
                "title_font_size": 14
            }
        },
        "abda3t_male": {
            "orientation": "landscape",
            "display_name": {
                "x": 400,
                "y": 355,
                "font_size": 31
            },
            "signatures": {
                "x_center": 400,
                "y_position": 120,
                "name_y": 95,
                "title_y": 80,
                "signature_width": 100,
                "signature_height": 50,
                "name_font_size": 18,
                "title_font_size": 14
            }
        },
        "abda3t_female": {
            "orientation": "landscape",
            "display_name": {
                "x": 400,
                "y": 355,
                "font_size": 31
            },
            "signatures": {
                "x_center": 400,
                "y_position": 120,
                "name_y": 95,
                "title_y": 80,
                "signature_width": 100,
                "signature_height": 50,
                "name_font_size": 18,
                "title_font_size": 14
            }
        },
        
    }
    
    default_config = {
        "orientation": "landscape",
        "display_name": {
            "x": 300,
            "y": 600,
            "font_size": 48
        },
        "signatures": {
            "x_center": 300,
            "y_position": 90,
            "name_y": 65,
            "title_y": 50,
            "signature_width": 120,
            "signature_height": 60,
            "name_font_size": 20,
            "title_font_size": 16
        }
    }
    
    return positioning_configs.get(request_type, default_config)


def make_grid_overlay(size, step=50, orientation="portrait"):

    if orientation == "landscape":
        width, height = size[1], size[0]
        page_size = landscape(size)
    else:
        width, height = size
        page_size = size
    
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=page_size)
    c.setFont("Helvetica", 6)
    
    for x in range(0, int(width), step):
        c.drawString(x, 5, str(x))
        c.line(x, 0, x, height)
    
    for y in range(0, int(height), step):
        c.drawString(5, y, str(y))
        c.line(0, y, width, y)
    
    c.save()
    packet.seek(0)
    return packet


async def gen_pdf(shortname: str, show_grid: bool = False, orientation: str = "portrait") -> StreamingResponse:
    

    request=await db.load(
        space_name='tamayyoz',
        subpath="/requests",
        shortname=shortname,
        class_type=core.Ticket,
    )

    request_payload = request.payload
    if request_payload is None or request_payload.body is None:
        raise api.Exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error=api.Error(
                type="request",
                code=InternalErrorCode.OBJECT_NOT_FOUND,
                message="Request payload or body is missing",
            ),
        )
    
    request_body = request_payload.body
    if not isinstance(request_body, dict):
        raise api.Exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error=api.Error(
                type="request",
                code=InternalErrorCode.OBJECT_NOT_FOUND,
                message="Request body is not a valid dictionary",
            ),
        )
    nominee_shortname = request_body.get("nominee_shortname", "")
    nominee = await db.load(
        space_name='management',
        subpath="/users",
        shortname=nominee_shortname,
        class_type=core.User,
    )
    request_type = request_body.get("type", "")
    if request_type == "3ashat_idak":
        pdf_template = await db.get_media_attachment(
            space_name='tamayyoz',
            subpath="/configurations/pdfs/pdf",
            shortname=f"{request_type}"
        )
    elif request_type == "grey" or request_type == "purple":
        raise api.Exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error=api.Error(
                type="request",
                code=InternalErrorCode.OBJECT_NOT_FOUND,
                message="Request type not supported",
            ),
        )
    else:
        request_type = f"{request_type}_{nominee.payload.body.get("gender", "")}"
        print(f"the request type is {request_type}")
        pdf_template = await db.get_media_attachment(
            space_name='tamayyoz',
            subpath="/configurations/pdfs/pdf",
            shortname=f"{request_type}"
        )
    if request.state != "approved" and request.state != "final_approval":
        raise api.Exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error=api.Error(
                type="request",
                code=InternalErrorCode.OBJECT_NOT_FOUND,
                message="Request is not approved or final approved",
            ),
        )
    user_shortnames = [h.user_shortname for h in (request.acl or [])]
    unique_user_shortnames = list(dict.fromkeys(user_shortnames))
    total, users = await db.query(api.Query(
        filter_shortnames=unique_user_shortnames,
        space_name="management",
        subpath="/users",
        type=QueryType.search,
        search="",
    ),"dmart")
    if total == 0:
        raise api.Exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error=api.Error(
                type="user",
                code=InternalErrorCode.OBJECT_NOT_FOUND,
                message="No users found for the given shortnames",
            ),
        )
    allowed_to_sign = ["hr_chief","chief","director","ceo"]


    if pdf_template is None:
        raise api.Exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error=api.Error(
                type="template",
                code=InternalErrorCode.OBJECT_NOT_FOUND,
                message="PDF template not found",
            ),
        )
    template_bytes = pdf_template.read()
    
    FONT_PATH = os.path.join(os.path.dirname(__file__), "Zain_Regular.ttf")
    pdfmetrics.registerFont(TTFont('Zain_Regular', FONT_PATH))
    FONT_PATH = os.path.join(os.path.dirname(__file__), "Zain_Light.ttf")
    pdfmetrics.registerFont(TTFont('Zain_Light', FONT_PATH))
    FONT_PATH = os.path.join(os.path.dirname(__file__), "NotoKufiArabic-Regular.ttf")
    pdfmetrics.registerFont(TTFont('NotoKufiArabic-Regular', FONT_PATH))
    FONT_PATH = os.path.join(os.path.dirname(__file__), "NotoKufiArabic-ExtraLight.ttf")
    pdfmetrics.registerFont(TTFont('NotoKufiArabic-ExtraLight', FONT_PATH))
    
    
    
    if nominee is None or nominee.displayname is None:
        raise api.Exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error=api.Error(
                type="nominee",
                code=InternalErrorCode.OBJECT_NOT_FOUND,
                message="Nominee not found or displayname missing",
            ),
        )
    
    displayname_ar = getattr(nominee.displayname, 'ar', '')
    if not displayname_ar:
        displayname_ar = nominee.shortname  
    
    reshaped_text = arabic_reshaper.reshape(displayname_ar)
    bidi_text = get_display(reshaped_text)
    print(repr(bidi_text))

    positioning_config = get_positioning_config(request_type)
    
    config_orientation = positioning_config.get("orientation", orientation)
    if config_orientation == "landscape":
        config_orientation = "landscape"
    else:
        config_orientation = "portrait"

    overlay_buffer = io.BytesIO()
    page_size = landscape(A4) if config_orientation == "landscape" else A4
    overlay_canvas = Canvas(overlay_buffer, pagesize=page_size)
    
    display_name_config = positioning_config["display_name"]
    overlay_canvas.setFont("NotoKufiArabic-Regular", display_name_config["font_size"])
    if request_type == "3ashat_idak":
        overlay_canvas.drawCentredString(display_name_config["x"], display_name_config["y"], bidi_text)
    else:
        overlay_canvas.drawRightString(display_name_config["x"], display_name_config["y"], bidi_text)
    
    signatory_count = 0
    total_signatories = len([u for u in users if any(role in allowed_to_sign for role in u.attributes.get("roles", []))])
    
    signature_config = positioning_config["signatures"]
    
    sig_width = signature_config["signature_width"]
    spacing = 50  
    total_width = (total_signatories * sig_width) + ((total_signatories - 1) * spacing)
    
    block_center_x = signature_config["x_center"]
    
    start_x = block_center_x - (total_width / 2)
    
    for user in users:
        user_roles = user.attributes.get("roles", [])
        if any(role in allowed_to_sign for role in user_roles):
            signature = await db.get_media_attachment(
                space_name="personal",
                subpath=f"people/{user.shortname}/private/signature",
                shortname="signature"
            )
            
            if signature is None:
                continue  
            signature_bytes = signature.read()                
            sig_image = ImageReader(io.BytesIO(signature_bytes))
            
            sig_x = start_x + (signatory_count * (sig_width + spacing))
            sig_y = signature_config["y_position"]
            sig_height = signature_config["signature_height"]
            
            overlay_canvas.drawImage(sig_image, sig_x, sig_y, width=sig_width, height=sig_height, preserveAspectRatio=True, mask="auto")
            
            name = get_display(arabic_reshaper.reshape(user.attributes.get('displayname', {}).get('ar', '')))
            title = get_display(arabic_reshaper.reshape(user.attributes.get('description', {}).get('ar', 'العنوان الوظيفي')))

            individual_center_x = sig_x + (sig_width / 2)
            
            overlay_canvas.setFont("NotoKufiArabic-Regular", signature_config["name_font_size"])
            overlay_canvas.drawCentredString(individual_center_x, signature_config["name_y"], name)
            overlay_canvas.setFont("NotoKufiArabic-ExtraLight", signature_config["title_font_size"])
            overlay_canvas.drawCentredString(individual_center_x, signature_config["title_y"], title)
            signatory_count += 1

    overlay_canvas.save()
    
    overlay_buffer.seek(0)
    overlay_bytes = overlay_buffer.getvalue()
    overlay_buffer.close()
    
    template_reader = PdfReader(io.BytesIO(template_bytes))
    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
    
    pdf_writer = PdfWriter()
    template_page = template_reader.pages[0]
    overlay_page = overlay_reader.pages[0]
    
    template_page.merge_page(overlay_page)
    
    if show_grid:
        grid_buffer = make_grid_overlay(A4, step=50, orientation=config_orientation)
        grid_reader = PdfReader(grid_buffer)
        grid_page = grid_reader.pages[0]
        template_page.merge_page(grid_page)
    
    pdf_writer.add_page(template_page)
    
    final_buffer = io.BytesIO()
    pdf_writer.write(final_buffer)
    final_buffer.seek(0)
    
    pdf_stream = io.BytesIO(final_buffer.getvalue())
    pdf_stream.seek(0)

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=report.pdf"}
    )


@router.get(
    "/certificate_gen/{shortname}",
    response_model_exclude_none=True,
)
async def get_pdf_api(
        shortname: str = Path(..., regex=regex.SHORTNAME),
        show_grid: bool = False,
        logged_in_user=Depends(JWTBearer()),
) -> StreamingResponse:
    
    return await gen_pdf(shortname, show_grid)