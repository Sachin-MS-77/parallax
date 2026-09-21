"""Paginated, locally generated case report with detached signature support."""
import io
from html import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def report_pdf(payload):
    output=io.BytesIO(); styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='SmallWrap',parent=styles['BodyText'],fontSize=8,leading=11,wordWrap='CJK'))
    doc=SimpleDocTemplate(output,pagesize=(595.28,841.89),rightMargin=42,leftMargin=42,topMargin=44,bottomMargin=44)
    story=[]
    def p(text, style='BodyText'): return Paragraph(escape(str(text)),styles[style])
    a=payload['alert']
    story += [p('PARALLAX | INVESTIGATION DOSSIER','Title'),p(payload['scope']),Spacer(1,14),
              p('Address and candidate entity','Heading2'),p(a['address'],'SmallWrap'),
              p(a.get('entity_id','Unresolved'),'SmallWrap'),p('Exported: '+payload['exported_at'],'SmallWrap')]
    table=Table([[p('Priority'),p('Evidence completeness'),p('Transactions')],
                 [p(f"{a['priority']}/100"),p(f"{a['evidence_quality']}/100"),p(a['tx_count'])]],colWidths=[170]*3)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4edf4')),('BOX',(0,0),(-1,-1),.5,colors.HexColor('#bac9d5')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story += [Spacer(1,12),table,p('Reasons for review','Heading2'),p(a.get('reason','See component evidence'))]
    for r in a['rules']: story += [p(r['name'],'Heading3'),p(r['reason'])]
    story.append(p('Model explanation','Heading2'))
    story.append(p('Tree SHAP values explain Isolation Forest mean path length. Negative values increase anomalousness. These are not causal claims.'))
    for e in a['explanations']:
        story.append(p(f"{e['feature']}: value {e['value']}; SHAP path-length contribution {e.get('shap_path_length','unavailable')}",'SmallWrap'))
    story.append(p('Uncertainty and alternative explanations','Heading2'))
    for c in a['caveats']: story.append(p(c))
    story += [p('Integrity and reproducibility','Heading2'),p('Model SHA-256: '+a['model_sha256'],'SmallWrap'),
              p('Audit head: '+payload['audit_anchor']['head'],'SmallWrap'),
              p('Verify report.pdf.sig against the exact PDF bytes using the separately trusted public key. The ZIP manifest also covers this PDF. This is a detached Ed25519 signature, not a PDF viewer certificate.')]
    story.append(p('Source references','Heading2'))
    for s in payload['sources']: story.append(p(s['name']+' | '+s['hash'],'SmallWrap'))
    story.append(p('Selected supporting observations','Heading2'))
    for o in payload['observations'][:20]:
        story.append(p(f"{o['timestamp']} | source row {o['source_row']} | TXID {o['txid']} | relay {o['src_ip']} -> {o['dst_ip']}",'SmallWrap'))
    if len(payload['observations'])>20:
        story.append(p(f"Showing 20 of {len(payload['observations'])} observations. Complete records and graph are preserved in signed case.json."))
    def footer(canvas,doc):
        canvas.saveState(); canvas.setFont('Helvetica',8); canvas.setFillColor(colors.HexColor('#526579'))
        canvas.drawString(42,25,'PARALLAX - Investigative lead for human review'); canvas.drawRightString(553,25,str(doc.page)); canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
