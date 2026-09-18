import base64, io, json, re
from pathlib import Path

def _decode_data_url(data):
    if "," in data: data=data.split(",",1)[1]
    return base64.b64decode(data)

def extract_document(filename, data_url, max_chars=80000):
    ext=Path(filename or "").suffix.lower()
    raw=_decode_data_url(data_url)
    text=""
    meta={"filename":filename,"extension":ext,"bytes":len(raw)}

    if ext==".pdf":
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw))
        parts=[]
        for i,p in enumerate(reader.pages[:120]):
            try: parts.append(f"\n--- PAGE {i+1} ---\n"+(p.extract_text() or ""))
            except Exception: pass
        text="".join(parts); meta["pages"]=len(reader.pages)
    elif ext==".docx":
        from docx import Document
        doc=Document(io.BytesIO(raw))
        text="\n".join(p.text for p in doc.paragraphs)
        meta["paragraphs"]=len(doc.paragraphs)
    elif ext==".xlsx":
        from openpyxl import load_workbook
        wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
        chunks=[]
        for ws in wb.worksheets[:30]:
            chunks.append(f"\n--- SHEET: {ws.title} ---")
            for row in ws.iter_rows(values_only=True):
                vals=[("" if v is None else str(v)) for v in row]
                chunks.append("\t".join(vals))
                if sum(len(x) for x in chunks)>max_chars: break
        text="\n".join(chunks); meta["sheets"]=wb.sheetnames
    elif ext==".pptx":
        from pptx import Presentation
        prs=Presentation(io.BytesIO(raw))
        chunks=[]
        for i,slide in enumerate(prs.slides):
            chunks.append(f"\n--- SLIDE {i+1} ---")
            for shape in slide.shapes:
                if hasattr(shape,"text") and shape.text:
                    chunks.append(shape.text)
        text="\n".join(chunks); meta["slides"]=len(prs.slides)
    else:
        text=raw.decode("utf-8",errors="replace")
    text=text[:max_chars]
    meta["extracted_chars"]=len(text)
    return {"text":text,"meta":meta}
