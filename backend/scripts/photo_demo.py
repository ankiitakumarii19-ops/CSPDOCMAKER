r"""Demo: every agent with a photo, through the live photo pipeline.

Makes each agent's AI studio portrait where it can (tracker No. 70) and
writes an HTML page showing original photo -> photo on documents -> ID Card.
Nothing is emailed or stored as a document. The page holds real agents'
photos: write it OUTSIDE the project folder.

    python scripts/photo_demo.py C:\CSPDOCMAKER-backups\photo-demo
"""
import base64
import io
import logging
import os
import sys

import pymupdf as fitz
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.services import (document_service, document_validation_service as dv,
                          face_match, pdf_service, photo_portrait,
                          studio_photo, template_service as t)
from app.workspace_context import all_workspaces

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
logging.basicConfig(level=logging.WARNING)
s = get_settings()
document_service.settings.document_output_dir = os.path.join(OUT, "docs")


def b64(img: Image.Image, width: int) -> str:
    img = img.copy()
    img.thumbnail((width, width * 2))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


rows = []
engine = create_engine(s.database_url.replace("postgresql+asyncpg://",
                                              "postgresql+psycopg2://"))
with Session(engine) as db, all_workspaces():
    agents = db.execute(select(CSPRecord).where(CSPRecord.photo_url != "")
                        .order_by(CSPRecord.csp_id)).scalars().all()
    for csp in agents:
        photo = csp.photo_url
        if not photo or not os.path.isfile(photo):
            continue
        portrait = photo_portrait.studio_portrait(photo)
        if portrait:
            used, how = portrait, "AI studio portrait (Cloudflare 9B)"
            try:
                how += f" — face match {face_match.similarity(photo, portrait):.2f}"
            except Exception:
                pass
        elif not photo_portrait.enabled():
            # No. 72: the AI is off; every photo is the white-background
            # passport photo made on this machine.
            used = studio_photo.make(photo)
            how = ("White-background passport photo, made on this laptop"
                   if used else "Original photo (no face found)")
            used = used or photo
        else:
            done, rejected = photo_portrait._cache_paths(photo)
            why = ("face did not match in 3 tries today — tried again tomorrow"
                   if os.path.exists(rejected)
                   else "AI not available now (free daily limit) — tried again later")
            print(f"{csp.csp_id} {csp.name[:24]:24} -> WAITING: {why}")
            rows.append(dict(id=csp.csp_id, name=csp.name, ok=None,
                             how=f"Waiting for AI portrait — {why}. Documents stay Pending.",
                             original=b64(Image.open(t.passport_crop(photo)), 260),
                             final=None, card=None))
            continue
        docs = document_service.generate_documents(
            csp, [DocumentType.CSP_ID_CARD])
        ok = dv.validate_all_documents(csp, docs)[0]
        (_, pdf), = pdf_service.convert_all([docs[0][1]],
                                            output_dir=os.path.join(OUT, "docs"))
        card = fitz.open(pdf)[0].get_pixmap(dpi=110)
        card_img = Image.open(io.BytesIO(card.tobytes("png")))
        print(f"{csp.csp_id} {csp.name[:24]:24} -> {how} | ID card valid: {ok}")
        rows.append(dict(
            id=csp.csp_id, name=csp.name, how=how, ok=ok,
            original=b64(Image.open(t.passport_crop(photo)), 260),
            final=b64(Image.open(t.passport_crop(used)), 260),
            card=b64(card_img, 520)))
    db.rollback()

cards = "\n".join(f"""
<section>
  <h2>{r['name']} <span>{r['id']}</span></h2>
  <p class="how">{r['how']}{'' if r['ok'] is None else ' · ID card validated: ' + ('yes' if r['ok'] else 'NO')}</p>
  <div class="row">
    <figure><img src="data:image/jpeg;base64,{r['original']}"><figcaption>Original photo</figcaption></figure>
    {'' if r['final'] is None else f"<figure><img src='data:image/jpeg;base64,{r['final']}'><figcaption>On the documents</figcaption></figure>"}
    {'' if r['card'] is None else f"<figure class='wide'><img src='data:image/jpeg;base64,{r['card']}'><figcaption>ID Card</figcaption></figure>"}
  </div>
</section>""" for r in rows)

html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Photo demo</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f3f4f6;margin:0;padding:24px;color:#111}}
h1{{margin:0 0 4px}} .sub{{color:#555;margin:0 0 24px}}
section{{background:#fff;border-radius:12px;padding:16px 20px;margin-bottom:18px;box-shadow:0 1px 3px #0002}}
h2{{margin:0;font-size:18px}} h2 span{{color:#888;font-weight:400;font-size:14px}}
.how{{margin:4px 0 12px;color:#0a7d3c;font-size:14px}}
.row{{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}}
figure{{margin:0;text-align:center}} figure img{{width:200px;border-radius:6px;border:1px solid #ddd}}
figure.wide img{{width:420px}} figcaption{{font-size:13px;color:#555;margin-top:4px}}
</style></head><body>
<h1>Agent photo demo</h1>
<p class="sub">Every agent with a photo, through exactly what the app does now. Nothing was emailed or saved as a document.</p>
{cards}
</body></html>"""
path = os.path.join(OUT, "photo-demo.html")
open(path, "w", encoding="utf-8").write(html)
print("DEMO", path)
