"""生成混合测试 PDF：覆盖服务需要自动识别的每一类页面。

用法: python make_sample.py out.pdf

一份 10 页的设备采购合同，每页内容不同：
  1-2 文字型（正文、含合并单元格的表格）  3 扫描（倾斜、噪点、红章、签章表）  4 扫描 + 旧 OCR 层（售后服务承诺）
  5 混合（正文 + 扫描的技术参数表 + 无文字的示意图）  6 乱码（字体缺少 ToUnicode，培训安排）  7 空白
  8 横向扫描（交付计划表）  9 扫描 + /Rotate 90（验收标准）  10 横着放的扫描页 + 红章（补充协议）
页面内容均为虚构。
"""

import random
import sys

import pymupdf

A4 = pymupdf.paper_rect("a4")

CSS = """
* { font-family: sans-serif; }
h1 { font-size: 20px; text-align: center; margin-bottom: 12px; }
h2 { font-size: 15px; margin: 10px 0 6px 0; }
p { font-size: 11px; line-height: 1.6; margin: 0 0 6px 0; }
table { border-collapse: collapse; width: 100%; margin: 6px 0; }
td, th { border: 1px solid #333; padding: 4px 6px; font-size: 10px; }
th { background: #eee; }
"""

CONTRACT_HTML = """
<h1>设备采购合同</h1>
<p>合同编号：CG-2026-0815　　签订日期：2026 年 8 月 15 日</p>
<p>甲方（采购方）：示例精密制造有限公司</p>
<p>乙方（供应方）：示例智能装备有限公司</p>
<h2>第一条　采购内容</h2>
<p>甲方向乙方采购以下设备，乙方保证所供设备为全新、未使用过的合格产品，符合国家及行业相关标准。</p>
<table>
<tr><th>序号</th><th>设备名称</th><th>型号</th><th>数量</th><th>单价（元）</th><th>金额（元）</th></tr>
<tr><td>1</td><td>数控加工中心</td><td>VMC-850</td><td>2</td><td>386,000.00</td><td>772,000.00</td></tr>
<tr><td>2</td><td>三坐标测量机</td><td>CMM-575</td><td>1</td><td>268,500.00</td><td>268,500.00</td></tr>
<tr><td>3</td><td>工业除尘系统</td><td>DC-3000</td><td>3</td><td>45,800.00</td><td>137,400.00</td></tr>
<tr><td colspan="5">合计（含税 13%）</td><td>1,177,900.00</td></tr>
</table>
<h2>第二条　交货与验收</h2>
<p>乙方应于合同签订后 45 个工作日内将设备运至甲方指定地点，并负责安装调试。甲方在设备安装调试完成后 10 个工作日内组织验收。</p>
"""

TERMS_HTML = """
<h2>第三条　付款方式</h2>
<p>1. 合同签订后 7 个工作日内，甲方支付合同总额的 30% 作为预付款，即人民币 353,370.00 元。</p>
<p>2. 设备验收合格后 15 个工作日内，甲方支付合同总额的 60%，即人民币 706,740.00 元。</p>
<p>3. 剩余 10% 作为质量保证金，质保期满且无质量问题后 10 个工作日内支付。</p>
<h2>第四条　质量保证</h2>
<p>设备质保期为验收合格之日起 24 个月。质保期内因设备本身质量问题造成的故障，乙方应在接到通知后 24 小时内响应，72 小时内到场维修，费用由乙方承担。</p>
<h2>第五条　违约责任</h2>
<p>乙方逾期交货的，每逾期一日按合同总额的 0.5‰ 向甲方支付违约金，逾期超过 30 日的，甲方有权解除合同。</p>
"""

SCAN_HTML = """
<h2>第六条　争议解决</h2>
<p>因本合同引起的或与本合同有关的任何争议，双方应友好协商解决；协商不成的，任何一方均可向甲方所在地人民法院提起诉讼。</p>
<h2>第七条　其他</h2>
<p>本合同一式肆份，甲乙双方各执贰份，具有同等法律效力。本合同自双方签字盖章之日起生效。</p>
<table>
<tr><th>甲方（盖章）</th><th>乙方（盖章）</th></tr>
<tr><td>法定代表人：张建华</td><td>法定代表人：李明远</td></tr>
<tr><td>开户银行：工商银行苏州分行</td><td>开户银行：建设银行苏州园区支行</td></tr>
<tr><td>账号：1102 0256 0900 1234 567</td><td>账号：3225 0198 8360 0000 1688</td></tr>
</table>
"""

SERVICE_HTML = """
<h1>附件二　售后服务承诺</h1>
<p>1. 乙方设立 7×24 小时售后服务热线 400-820-6688，接到报修后 2 小时内给出处理方案。</p>
<p>2. 乙方在苏州设有备件库，常用备品备件保证供应 8 年，停产前 12 个月书面通知甲方。</p>
<p>3. 质保期满后，乙方按成本价提供维修服务，人工费每人每天不超过 1,200 元。</p>
<p>4. 乙方每年免费上门巡检 2 次，出具巡检报告并提出保养建议。</p>
"""

ATTACHMENT_HTML = """
<h1>附件一　设备技术参数</h1>
<table>
<tr><th>参数</th><th>VMC-850</th><th>CMM-575</th><th>DC-3000</th></tr>
<tr><td>工作行程（mm）</td><td>800×500×550</td><td>500×700×500</td><td>—</td></tr>
<tr><td>定位精度（mm）</td><td>±0.005</td><td>1.9+L/300 μm</td><td>—</td></tr>
<tr><td>主轴转速（rpm）</td><td>12,000</td><td>—</td><td>—</td></tr>
<tr><td>处理风量（m³/h）</td><td>—</td><td>—</td><td>3,000</td></tr>
<tr><td>额定功率（kW）</td><td>15</td><td>2.5</td><td>5.5</td></tr>
</table>
"""

# 乱码页的原文（提取出来是乱码，只能靠 OCR）
TRAINING_LINES = [
    "附件三　培训安排",
    "1. 乙方在设备验收前对甲方操作人员进行现场操作培训，不少于 3 天。",
    "2. 培训内容包括设备操作、日常保养、常见故障排除和安全规范。",
    "3. 培训名额为甲方指定的 8 名操作人员和 2 名设备管理员。",
    "4. 培训结束后乙方组织考核，考核合格者颁发操作合格证书。",
    "5. 培训期间乙方提供中文操作手册和维护手册各 2 套。",
]

DELIVERY_HTML = """
<h1>附件四　交付计划</h1>
<table>
<tr><th>批次</th><th>设备</th><th>数量</th><th>到货日期</th><th>安装调试完成</th><th>交付地点</th></tr>
<tr><td>第一批</td><td>数控加工中心 VMC-850</td><td>2</td><td>2026-09-20</td><td>2026-09-30</td><td>甲方一号厂房</td></tr>
<tr><td>第二批</td><td>三坐标测量机 CMM-575</td><td>1</td><td>2026-10-10</td><td>2026-10-18</td><td>甲方计量室</td></tr>
<tr><td>第三批</td><td>工业除尘系统 DC-3000</td><td>3</td><td>2026-10-15</td><td>2026-10-25</td><td>甲方一号厂房</td></tr>
</table>
"""

ACCEPTANCE_HTML = """
<h1>附件五　验收标准</h1>
<p>1. 外观验收：设备无磕碰、锈蚀，随机附件、资料与装箱单一致。</p>
<p>2. 精度验收：按附件一的技术参数逐项检测，定位精度检测采用激光干涉仪。</p>
<p>3. 试运行：设备连续试运行 72 小时无故障，视为试运行合格。</p>
<p>4. 验收结论由双方签署验收报告确认；甲方逾期未组织验收的，视为验收合格。</p>
"""

SUPPLEMENT_HTML = """
<h1>补充协议</h1>
<p>经双方协商，对《设备采购合同》（编号 CG-2026-0815）补充约定如下：</p>
<p>1. 三坐标测量机 CMM-575 的到货日期由 2026 年 10 月 10 日调整为 2026 年 10 月 25 日。</p>
<p>2. 因上述调整，第二笔付款节点相应顺延，其余条款不变。</p>
<p>3. 本补充协议与原合同具有同等法律效力，自双方盖章之日起生效。</p>
<p>甲方：示例精密制造有限公司　　乙方：示例智能装备有限公司</p>
<p>日期：2026 年 9 月 28 日</p>
"""


def html_page(doc, html, rect=A4, margin=50):
    page = doc.new_page(width=rect.width, height=rect.height)
    page.insert_htmlbox(page.rect + (margin, margin, -margin, -margin), html, css=CSS)
    return page


def render_scan(html, rect=A4, dpi=150, angle=0.6, seal=True):
    """把 HTML 渲染成「扫描件」图片：灰度、轻微倾斜、噪点、红色印章。"""
    tmp = pymupdf.open()
    page = html_page(tmp, html, rect)
    if seal:
        center = pymupdf.Point(rect.width * 0.68, rect.height * 0.42)
        page.draw_circle(center, 48, color=(0.85, 0.1, 0.1), width=2.5)
        page.insert_htmlbox(
            pymupdf.Rect(center.x - 40, center.y - 12, center.x + 40, center.y + 12),
            '<p style="color:#d81a1a;font-size:11px;text-align:center;font-weight:bold">合同专用章</p>',
        )
    pix = page.get_pixmap(dpi=dpi)
    # 轻微旋转（模拟扫描倾斜）：用 MuPDF 重新绘制到新页面后再渲染
    rotated = pymupdf.open()
    rp = rotated.new_page(width=rect.width, height=rect.height)
    rp.show_pdf_page(rp.rect, tmp, 0, rotate=angle)
    pix = rp.get_pixmap(dpi=dpi)
    # 噪点
    random.seed(7)
    samples = bytearray(pix.samples)
    for _ in range(pix.width * pix.height // 60):
        i = random.randrange(0, len(samples) - 3, 3)
        v = random.randint(140, 220)
        samples[i : i + 3] = bytes((v, v, v))
    return pymupdf.Pixmap(pix.colorspace, pix.width, pix.height, bytes(samples), pix.alpha).tobytes("jpeg", 80)


def scan_page(doc, html, rect=A4, **kwargs):
    page = doc.new_page(width=rect.width, height=rect.height)
    page.insert_image(page.rect, stream=render_scan(html, rect, **kwargs))
    return page


def photo():
    """没有文字的「照片」：几个色块和圆形。"""
    tmp = pymupdf.open()
    page = tmp.new_page(width=300, height=180)
    page.draw_rect(page.rect, color=None, fill=(0.85, 0.9, 0.95))
    page.draw_rect(pymupdf.Rect(30, 90, 140, 160), color=None, fill=(0.3, 0.45, 0.7))
    page.draw_rect(pymupdf.Rect(160, 60, 270, 160), color=None, fill=(0.55, 0.6, 0.65))
    page.draw_circle(pymupdf.Point(230, 40), 22, color=None, fill=(0.95, 0.75, 0.2))
    return page.get_pixmap(dpi=150).tobytes("jpeg", 85)


def garbled_page():
    """单独生成后删除字体的 ToUnicode，避免和其他页共用同一个字体对象。"""
    tmp = pymupdf.open()
    page = tmp.new_page(width=A4.width, height=A4.height)
    page.insert_font(fontname="F1", fontbuffer=pymupdf.Font("cjk").buffer)
    for i, line in enumerate(TRAINING_LINES):
        size = 16 if i == 0 else 11
        page.insert_text((50, 80 + i * 24), line, fontname="F1", fontsize=size)
    tmp = pymupdf.open("pdf", tmp.tobytes())
    for font in tmp[0].get_fonts():
        tmp.xref_set_key(font[0], "ToUnicode", "null")
    return tmp


def main(out):
    doc = pymupdf.open()

    # 1-2. 文字型页（含表格）
    html_page(doc, CONTRACT_HTML)
    html_page(doc, TERMS_HTML)

    # 3. 扫描页（倾斜 + 噪点 + 红章）
    scan_page(doc, SCAN_HTML)

    # 4. 扫描页，带一层质量很差的旧 OCR 隐藏文字
    page = scan_page(doc, SERVICE_HTML, seal=False, angle=-0.4)
    page.insert_text((60, 120), "附件二 售后眼务承诺 1. 乙方设立 7x24 小时售后服务热钱", fontname="china-s", fontsize=11, render_mode=3)

    # 5. 混合页：正文 + 一张扫描的附件表格图片
    page = html_page(doc, "<h2>第八条　附件</h2><p>以下附件为本合同不可分割的组成部分，与本合同具有同等法律效力：</p>")
    img = render_scan(ATTACHMENT_HTML, pymupdf.Rect(0, 0, 595, 330), dpi=150, angle=0.3, seal=False)
    page.insert_image(pymupdf.Rect(50, 140, 545, 470), stream=img)
    # 一张没有文字的示意图（占页面 10% 以上，会被送去 OCR，但识别不出文字，Word 中应保留为图片）
    page.insert_image(pymupdf.Rect(50, 490, 350, 670), stream=photo())

    # 6. 乱码页：字体缺少 ToUnicode 编码映射，提取出来是乱码
    doc.insert_pdf(garbled_page())

    # 7. 空白页
    doc.new_page(width=A4.width, height=A4.height)

    # 8. 横向扫描页
    scan_page(doc, DELIVERY_HTML, rect=pymupdf.paper_rect("a4-l"), seal=False, angle=0.2)

    # 9. 扫描页：图片横着存储，页面带 /Rotate 90，显示是正的（很多扫描仪生成这种 PDF）
    page = doc.new_page(width=A4.height, height=A4.width)
    page.insert_image(page.rect, stream=render_scan(ACCEPTANCE_HTML, seal=False, angle=0.3), rotate=90)
    page.set_rotation(90)

    # 10. 扫描页：整页横着（扫描时放反了方向），需要 OCR 先转正
    page = doc.new_page(width=A4.height, height=A4.width)
    page.insert_image(page.rect, stream=render_scan(SUPPLEMENT_HTML, angle=-0.2), rotate=90)

    doc.save(out, garbage=4, deflate=True)
    print(f"saved {out}: {doc.page_count} pages")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample-mixed.pdf")
