"""Small generated test tables, not analysis assets."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

folder = Path('state/task15-refinement/fixtures')
folder.mkdir(parents=True, exist_ok=True)
(folder/'players.csv').write_text('\ufeff玩家编号,发生时间,活动名称,版本,时长\n001,2025-01-01,"探索,收集",V5,35\n002,2025-01-02,"地图探索\n素材收集",V6,45\n003,2025-01-03,战斗挑战,V6,25\n', encoding='utf-8')
(folder/'unsafe.csv').write_text('id,content\n001,<script>alert(1)</script>\n',encoding='utf-8')
(folder/'invalid.csv').write_text('id,event\n1,"unfinished', encoding='utf-8')
(folder/'empty.csv').write_text('', encoding='utf-8')
(folder/'旧版.xls').write_text('not a supported file', encoding='utf-8')
(folder/'中文.csv').write_bytes('编号,名称\n001,探索\n'.encode('gb18030'))
group=folder/'folder'
group.mkdir(exist_ok=True)
(group/'part-1.csv').write_text('id,activity\n001,explore\n',encoding='utf-8')
(group/'part-2.csv').write_text('player,time\n002,2025-01-02\n',encoding='utf-8')
(group/'notes.txt').write_text('skip me',encoding='utf-8')
ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
with ZipFile(folder/'players.xlsx','w',ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    z.writestr('_rels/.rels',f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets><sheet name="玩家" sheetId="1" r:id="rId1"/><sheet name="活动" sheetId="2" r:id="rId2"/></sheets></workbook>')
    z.writestr('xl/_rels/workbook.xml.rels',f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{rel}/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
    for i, title in enumerate(['玩家编号','活动编号'],1):
        z.writestr(f'xl/worksheets/sheet{i}.xml',f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>{title}</t></is></c><c r="B1" t="inlineStr"><is><t>次数</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>001</t></is></c><c r="B2"><v>12</v></c></row></sheetData></worksheet>')
print(folder)
