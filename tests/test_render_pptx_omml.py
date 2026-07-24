"""render_pptx OMML 注入的 schema 校验。

背景：Mac PowerPoint 对公式结构极敏感——必须是 a14:m > m:oMathPara > m:oMath
裸注入（不能包 mc:AlternateContent），每个 m:r 带 Cambria Math 的 a:rPr、每个
结构元素的 *Pr 带 m:ctrlPr、m:rad 带空 m:deg + degHide，缺任何一项 Mac 会
静默把 math zone 丢成空盒子。这些断言把「Mac 原生字节模式」固化成回归测试。

依赖 latex2mathml/mathml2omml/python-pptx（render_pptx 运行时依赖，未进项目
venv，缺则 skip）。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("lxml")
pytest.importorskip("latex2mathml")
pytest.importorskip("mathml2omml")

from lxml import etree  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent / "ethan/defaults/skills/ppt-generate/scripts"
sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("render_pptx", SCRIPTS / "render_pptx.py")
render_pptx = importlib.util.module_from_spec(spec)
sys.modules["render_pptx"] = render_pptx
spec.loader.exec_module(render_pptx)

qn = render_pptx.qn
A14_NS = render_pptx.A14_NS


def _macified(latex: str):
    """走完整链路：latex → OMML → 拆箱 → macify，返回 m:oMath 元素。"""
    omml = render_pptx.latex_to_omml(latex)
    wrapped = (f'<root xmlns:m="{render_pptx.M_NS}" '
               f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">{omml}</root>')
    omath = etree.fromstring(wrapped.encode("utf-8"))[0]
    render_pptx._unwrap_math_boxes(omath)
    render_pptx._macify_omml(omath, 20.0, "#1F2937")
    return omath


def test_math_boxes_unwrapped():
    omath = _macified(r"\frac{\sqrt{a^2+b^2}}{2}")
    assert not list(omath.iter(qn("m:box"))), "m:box 未拆干净（Mac 会渲染出边框）"


def test_runs_carry_native_arpr():
    omath = _macified(r"\sqrt{x} + y_1")
    runs = [r for r in omath.iter(qn("m:r")) if r.find(qn("m:t")) is not None]
    assert runs
    for r in runs:
        assert r.find(qn("m:rPr")) is None, "Mac 原生公式没有 m:rPr"
        arpr = r.find(qn("a:rPr"))
        assert arpr is not None, "每个 m:r 必须带 a:rPr（sz + solidFill + Cambria Math）"
        assert arpr.get("sz")
        latin = arpr.find(qn("a:latin"))
        assert latin is not None and latin.get("typeface") == "Cambria Math"


def test_italic_goes_to_arpr_i_attr():
    omath = _macified(r"\sqrt{x}")
    arprs = [r.find(qn("a:rPr")) for r in omath.iter(qn("m:r"))]
    assert any(a is not None and a.get("i") == "1" for a in arprs), "m:sty i 应转为 a:rPr i=1"


def test_struct_elements_have_ctrlpr():
    omath = _macified(r"\frac{\sqrt[3]{x}}{\sum_{i=1}^{n} y_i^2}")
    for struct_tag, pr_tag in render_pptx._MATH_STRUCT_PR.items():
        for struct in omath.iter(qn(struct_tag)):
            pr = struct.find(qn(pr_tag))
            assert pr is not None, f"{struct_tag} 缺 {pr_tag}"
            ctrl = pr.find(qn("m:ctrlPr"))
            assert ctrl is not None, f"{pr_tag} 缺 m:ctrlPr（Mac 静默丢公式的元凶）"
            assert ctrl.find(qn("a:rPr")) is not None


def test_rad_has_deghide_and_empty_deg():
    omath = _macified(r"\sqrt{x}")
    rads = list(omath.iter(qn("m:rad")))
    assert rads
    for rad in rads:
        pr = rad.find(qn("m:radPr"))
        assert pr is not None
        deghide = pr.find(qn("m:degHide"))
        assert deghide is not None and deghide.get(qn("m:val")) == "on"
        # 子元素顺序：radPr? deg? e —— 空 m:deg 必须在 m:e 之前
        tags = [etree.QName(c).localname for c in rad]
        assert "deg" in tags and tags.index("deg") < tags.index("e")


def test_a14m_bare_injection():
    """完整渲染一页 latex 元素，断言段落里是裸 a14:m > m:oMathPara > m:oMath，
    没有 mc:AlternateContent（Mac 遇到 Requires="a14" 的 Choice 会选 Fallback 显示纯文本）。"""
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    el = {"id": "f1", "type": "latex", "left": 100, "top": 100, "width": 600, "height": 80,
          "latex": r"e^{i\pi} + 1 = 0", "fontSize": 24, "color": "#1F2937"}
    render_pptx._render_latex_omml(slide, el, {}, 12192.0)
    xml = slide.shapes[-1]._element.xml
    assert f"{{{A14_NS}}}m" in xml or "a14:m" in xml
    assert "oMathPara" in xml
    assert "AlternateContent" not in xml
