import io
import re
import json
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image, ImageDraw
from pdf2image import convert_from_bytes

# PDF 생성 관련 라이브러리
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ==========================================
# 1. 페이지 기본 설정 및 디자인
# ==========================================
st.set_page_config(
    page_title="실내재료마감표 AI 유연 비교 검토 시스템",
    layout="wide"
)

st.title("🏗️ 실내재료마감표 AI 유연 비교 검토 시스템1")
st.write("표준 도면과 검토 대상 도면의 **행 순서/양식이 달라도 실명(공간명) 기준 교차 매칭**하여 정밀 분석 및 컬러 하이라이트를 생성합니다.")

# ==========================================
# 2. 파일 변환 및 PDF 리포트 생성 헬퍼 함수
# ==========================================
def load_all_as_images(uploaded_file):
    """PDF(모든 페이지) 또는 이미지를 PIL Image 객체 리스트로 안전하게 변환합니다."""
    file_bytes = uploaded_file.read()
    if uploaded_file.name.lower().endswith(".pdf"):
        images = convert_from_bytes(file_bytes, dpi=200)
        return images
    else:
        return [Image.open(io.BytesIO(file_bytes))]

def draw_color_blocks_multi(image_list, markdown_text):
    """AI 응답 텍스트 숨김 주석에서 좌표를 파싱하여 도면 이미지 위에 반투명 컬러 블록을 그립니다."""
    processed_images = []
    
    color_map = {
        "RED": (255, 50, 50, 90),     # 반투명 빨강
        "YELLOW": (255, 200, 0, 90),  # 반투명 노랑
        "BLUE": (0, 150, 255, 80)     # 반투명 파랑
    }

    overlays = [Image.new("RGBA", img.size, (255, 255, 255, 0)) for img in image_list]
    draws = [ImageDraw.Draw(ov) for ov in overlays]
    
    lines = markdown_text.split('\n')
    
    for line in lines:
        if "|" in line or "<!-- BBOX:" in line:
            # 숨김 좌표 패턴 추출 <!-- BBOX: [ymin, xmin, ymax, xmax] --> 또는 [ymin, xmin, ymax, xmax]
            coords = re.findall(r'\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]', line)
            page_match = re.search(r'Page\s*(\d+)|페이지\s*(\d+)', line, re.IGNORECASE)
            page_idx = 0
            if page_match:
                p_num = page_match.group(1) or page_match.group(2)
                page_idx = max(0, int(p_num) - 1)
            
            if page_idx >= len(image_list):
                page_idx = 0

            if coords:
                ymin, xmin, ymax, xmax = map(int, coords[0])
                
                box_color = (255, 0, 0, 90)
                for key, color in color_map.items():
                    if key in line:
                        box_color = color
                        break
                
                w, h = image_list[page_idx].size
                
                x1 = int(max(0, min(1000, xmin)) * w / 1000)
                y1 = int(max(0, min(1000, ymin)) * h / 1000)
                x2 = int(max(0, min(1000, xmax)) * w / 1000)
                y2 = int(max(0, min(1000, ymax)) * h / 1000)
                
                if x2 - x1 < 15: x2 = min(w, x1 + 30)
                if y2 - y1 < 10: y2 = min(h, y1 + 25)
                
                draws[page_idx].rectangle([x1, y1, x2, y2], fill=box_color, outline=(box_color[0], box_color[1], box_color[2], 255), width=3)

    for idx, base_img in enumerate(image_list):
        img_rgba = base_img.convert("RGBA")
        result_img = Image.alpha_composite(img_rgba, overlays[idx])
        processed_images.append(result_img.convert("RGB"))

    return processed_images

def create_pdf_report(result_images, result_text):
    """검토 결과 이미지들과 텍스트를 포함하는 PDF 문서를 생성합니다."""
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, leading=22, textColor=colors.HexColor('#1E3A8A'))
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontSize=9, leading=13)
    
    story.append(Paragraph("<b>[AI Document Review] 실내재료마감표 검토 보고서</b>", title_style))
    story.append(Spacer(1, 15))
    
    for idx, img in enumerate(result_images):
        story.append(Paragraph(f"<b>■ 검토 도면 시각화 오버레이 (Page {idx+1})</b>", normal_style))
        story.append(Spacer(1, 5))
        
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        w, h = img.size
        aspect = h / float(w)
        target_w = 520
        target_h = target_w * aspect
        
        story.append(RLImage(img_buffer, width=target_w, height=target_h))
        story.append(Spacer(1, 15))
    
    story.append(Paragraph("<b>■ 세부 검토 요약 및 비교 분석 결과</b>", normal_style))
    story.append(Spacer(1, 5))
    
    # HTML 주석 제거 및 마크다운 정리
    clean_text = re.sub(r'<!--.*?-->', '', result_text)
    clean_lines = clean_text.split('\n')
    for line in clean_lines:
        line_str = line.strip()
        if line_str.startswith("#"):
            line_str = f"<b>{line_str.replace('#', '').strip()}</b>"
        elif line_str.startswith("-"):
            line_str = f"• {line_str[1:].strip()}"
        
        line_str = line_str.replace('<', '&lt;').replace('>', '&gt;')
        story.append(Paragraph(line_str if line_str else "&nbsp;", normal_style))
        story.append(Spacer(1, 2))
        
    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

# ==========================================
# 3. 사이드바 - API Key 및 검토 안내
# ==========================================
with st.sidebar:
    st.header("🔑 설정")
    api_key = st.text_input("Google API Key를 입력하세요", type="password")
    st.markdown("[API Key 발급받기](https://aistudio.google.com/app/apikey)")
    st.divider()
    st.markdown("""
    **🎨 색상 등급 분류 엄격 기준**
    - 🔴 **RED (사양 변경 - 필수)**: 
      - 마감재 재질 변경 (예: 강마루 ↔ 타일)
      - **방수 공법/스펙 변경 (예: 노출우레탄 ↔ 비노출+무근콘크리트)**
    - 🟡 **YELLOW (표기 차이)**: 동의어(욕실=화장실) 및 단순 양식 차이
    - 0️⃣ **BLUE (구조/신설)**: 신규 실/테이블 추가, 실 위치 이동, NOTE 주기사항 변경
    """)

# ==========================================
# 4. 도면 파일 업로드 구역
# ==========================================
col1, col2 = st.columns(2)
with col1:
    std_file = st.file_uploader("1. 표준 실내재료마감표 (이미지/PDF)", type=["png", "jpg", "jpeg", "pdf"])
with col2:
    target_file = st.file_uploader("2. 검토 대상 도면 (다중페이지 PDF/이미지)", type=["png", "jpg", "jpeg", "pdf"])

# ==========================================
# 5. Google AI Studio 교차 매칭 지침(System Instructions)
# ==========================================
FULL_SYSTEM_INSTRUCTIONS = """
역할 및 목표:
당신은 건축 실시설계 도면 검토 전문가입니다.
[표준 도면]과 [검토 대상 도면]의 **행 위치나 양식이 서로 다르더라도, 반드시 '실명/공간명(예: 현관, 거실, 지붕 등)'을 기준으로 Cross-Matching(1:1 교차 비교)하여 정밀 분석**하세요.

1. 교차 매칭(Cross-Matching) 절대 원칙 (위치 오독 방지):
   - **순서 불일치 무시**: 두 도면의 표 순서나 행 위치가 다르더라도 같은 실명을 찾아 마감재 스펙을 1:1 비교하세요.
   - **신규 실/표 추가**: 표준 도면에 없으나 검토 대상 도면에 새로 추가된 실/테이블은 불일치가 아닌 🔵 BLUE (구조/신설)로 처리하세요.

2. 색상 및 등급 분류 기준:
   - 🔴 RED (실제 재질/사양/방수 변경):
     * 마감 재질 변경 (예: 강마루 → 타일, 수성페인트 → 에폭시)
     * **방수 공법 및 구조 변경 (예: 노출우레탄 방수 → 비노출우레탄 + 무근콘크리트)은 예외 없이 🔴 RED로 분류**
   - 🟡 YELLOW (동의어/표기 방식 차이):
     * 실질 사양은 동일하나 용어 차이 (예: '욕실' ↔ '화장실') 및 셀 병합 양식 차이
   - 🔵 BLUE (구조/신설/주석 변경):
     * 실 신설, 별도 마감표 추가, NOTE 주기사항 변경

3. 하이라이트 좌표 추정 규칙 (화면 숨김 처리):
   - [검토 대상 도면]에서 해당 변경 사항이 실제로 위치한 행 전체 셀 또는 텍스트 구역의 Bounding Box 상대 좌표 `[ymin, xmin, ymax, xmax]` (0~1000 정수)를 계산하세요.
   - **중요**: 비교표 내부 열(Column)에 좌표를 노출하지 말고, 표의 마지막 열 끝에 HTML 주석 형식 `<!-- BBOX: Page X [ymin, xmin, ymax, xmax] -->`로 숨겨서 출력하세요.

출력 형식 (Output Format):
반드시 아래 마크다운 양식으로만 답변을 작성하세요. (표에 좌표 열을 만들지 마세요)

---
## 🏗️ 실내재료마감표 AI 유연 비교 검토 결과

### 1. 검토 요약
- 🔴 **실제 사양 변경 (RED):** X건
- 🟡 **용어/표현 차이 (YELLOW):** X건
- 🔵 **구조 및 주석 변경 (BLUE):** X건

---

### 2. 세부 차이점 비교표

| 분류 등급 | 대상 페이지 | 구획 / 실명 | 부위 (바닥/벽/천장) | 표준 도면 사양 | 검토 대상 도면 사양 | 변경 내용 및 검토 의견 |
| :---: | :---: | :--- | :--- | :--- | :--- | :--- |
| 🔴 RED | Page 1 | 지붕(평지붕) | 바닥 바탕 | 노출우레탄 방수 | 비노출우레탄+무근콘크리트 | [사양 변경] 방수 공법이 노출에서 비노출+무근 구조로 변경됨 <!-- BBOX: Page 1 [700, 180, 755, 835] --> |
| 🟡 YELLOW | Page 1 | 거실/침실 | 걸레받이 바탕 | 콘크리트면처리 or 석고보드 | 지정 걸레받이 | [표기 차이] 셀 병합 구조 차이로 동일 사양 간주 <!-- BBOX: Page 1 [100, 340, 140, 520] --> |
| 🔵 BLUE | Page 2 | 외벽 / 측벽 | 하단 별도 표기 | 기본 표 포함 | 외벽 마감표 별도 분리 신설 | [구조 변경] 외벽 마감 별도 테이블 추가됨 <!-- BBOX: Page 2 [895, 360, 934, 638] --> |

---

### 3. 검토 총평 및 조치 권고사항
(전체적인 도면 변경 경향 및 현장 확인이 필요한 핵심 사안을 2~3줄로 요약 작성)
"""

# ==========================================
# 6. AI 검토 실행 로직
# ==========================================
if st.button("🚀 AI 도면 비교 검토 시작", use_container_width=True):
    if not api_key:
        st.error("왼쪽 사이드바에 Google API Key를 입력해 주세요.")
    elif not std_file or not target_file:
        st.warning("두 도면 파일을 모두 업로드해 주세요.")
    else:
        with st.spinner("Gemini 3.5 Flash Lite 모델이 공간명 기준 1:1 교차 분석 중입니다..."):
            try:
                client = genai.Client(api_key=api_key)
                
                std_imgs = load_all_as_images(std_file)
                target_imgs = load_all_as_images(target_file)

                input_contents = []
                input_contents.append("--- [표준 실내재료마감표 도면] ---")
                input_contents.extend(std_imgs)
                input_contents.append("--- [검토 대상 도면 (전체 페이지)] ---")
                input_contents.extend(target_imgs)
                input_contents.append("표의 순서가 다르더라도 동일한 실명을 찾아 1:1 교차 비교 분석을 진행하고 결과를 작성해 주세요.")

                response = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=input_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=FULL_SYSTEM_INSTRUCTIONS,
                        temperature=0.0
                    )
                )

                result_overlay_imgs = draw_color_blocks_multi(target_imgs, response.text)
                
                st.success("✅ 공간명 교차 검증 및 하이라이트 생성이 완료되었습니다!")
                
                # PDF 리포트 생성 및 다운로드 버튼
                pdf_bytes = create_pdf_report(result_overlay_imgs, response.text)
                st.download_button(
                    label="📄 검토 결과 PDF 보고서 다운로드",
                    data=pdf_bytes,
                    file_name="실내재료마감표_AI_검토보고서.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
                
                st.divider()

                # 1. 다중 페이지 이미지 결과 출력
                st.subheader("🎨 검토 도면 시각화 오버레이 (페이지별 결과)")
                page_tabs = st.tabs([f"📄 Page {i+1}" for i in range(len(result_overlay_imgs))])
                for i, tab in enumerate(page_tabs):
                    with tab:
                        st.image(result_overlay_imgs[i], caption=f"검토 대상 도면 Page {i+1} 하이라이트", use_container_width=True)
                
                st.divider()

                # 2. 좌표가 숨겨진 깨끗한 표 및 총평 출력
                # HTML 주석(<!-- BBOX: ... -->)을 제거하여 깔끔한 표만 사용자에게 노출
                clean_markdown = re.sub(r'<!-- BBOX:.*?-->', '', response.text)
                st.markdown(clean_markdown)

            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
