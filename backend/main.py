"""FastAPI: серверный разбор контрольных размеров."""

from fastapi import FastAPI

from backend.config import get_settings
from backend.errors import install_error_handlers
from backend.models import ParseRequest, ParseResponse
from backend.parsing import make_checklist, parse_dimensions

app = FastAPI(title="Чертёжник API")
install_error_handlers(app)


@app.post("/parse-dimensions", response_model=ParseResponse)
async def parse_dimensions_endpoint(request: ParseRequest) -> ParseResponse:
    dimensions = parse_dimensions(request.raw_text, get_settings())
    return ParseResponse(dimensions=dimensions, checklist=make_checklist(dimensions))
