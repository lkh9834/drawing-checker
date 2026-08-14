import io
import re
import json
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image, ImageDraw
from pdf2image import convert_from_bytes

# PDF 생성 관련 라이브러리
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ==========================================
# 1. 페이지 기본 설정 및 디자인
# ==========================================
st.set_page_config(
    page_title="실내재료마감표 AI 유연 비교 검토 시스템",
    layout="wide"
)

st.title("🏗️ 실내재료마감표 AI 유연 비교 검토 시스템")
st.write("표준 도면 이미지/PDF와 검토 대상 도면(다중 페이지 PDF/이미지)을 업로드하면, AI가 전체 페이지를 전수 분석하여 **컬러 블록 하이라이트 도면**과 세부 비교표를 생성합니다.")

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
    """AI 응답 텍스트에서 상대 좌표를 파싱하여 도면 이미지 위에 반투명 컬러 블록을 그립니다."""
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
        if "|" in line:
            coords = re.findall(r'\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]', line)
            page_match = re.search(r'\(?페이지\s*(\d+)\)?|Page\s*(\d+)', line, re.IGNORECASE)
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
                
                if x2 - x1 < 10: x2 = min(w, x1 + 20)
                if y2 - y1 < 10: y2 = min(h, y1 + 20)
                
                draws[page_idx].rectangle([x1, y1, x2, y2], fill=box_color, outline=(box_color[0], box_color[1], box_color[2], 255), width=3)

    for idx, base_img in enumerate(image_list):
        img_rgba = base_img.convert("RGBA")
        result_img = Image.alpha_composite(img_rgba, overlays[idx])
        processed_images.append(result_img.convert("RGB"))

    return processed_images

def create_pdf_report(result_images, result_text):
    """검토 결과 이미지들과 텍스트를 포함하는 PDF 문서를 메모리 상에서 생성합니다."""
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, leading=22, textColor=colors.HexColor('#1E3A8A'))
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontSize=9, leading=13)
    
    # 1. 제목 및 헤더
    story.append(Paragraph("<b>[AI Document Review] 실내재료마감표 검토 보고서</b>", title_style))
    story.append(Spacer(1, 15))
    
    # 2. 하이라이트 도면 이미지 삽입 (페이지별)
    for idx, img in enumerate(result_images):
        story.append(Paragraph(f"<b>■ 검토 도면 시각화 오버레이 (Page {idx+1})</b>", normal_style))
        story.append(Spacer(1, 5))
        
        # 이미지를 PDF 크기에 맞춰 리사이징
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        # A4 폭(535pt) 기준 비율 맞춤
        w, h = img.size
        aspect = h / float(w)
        target_w = 520
        target_h = target_w * aspect
        
        story.append(RLImage(img_buffer, width=target_w, height=target_h))
        story.append(Spacer(1, 15))
    
    # 3. 마크다운 검토 텍스트 정리 및 삽입
    story.append(Paragraph("<b>■ 세부 검토 요약 및 비교 분석 결과</b>", normal_style))
    story.append(Spacer(1, 5))
    
    clean_lines = result_text.split('\n')
    for line in clean_lines:
        line_str = line.strip()
        if line_str.startswith("#"):
            line_str = f"<b>{line_str.replace('#', '').strip()}</b>"
        elif line_str.startswith("-"):
            line_str = f"• {line_str[1:].strip()}"
        
        # HTML 태그 이스케이프 기본 처리
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
      - 두께, 도장 종류 변경
    - 🟡 **YELLOW (표기 차이)**: 동의어(욕실=화장실) 및 셀 병합에 따른 단순 양식 차이
    - 🔵 **BLUE (구조/위치/주석)**: 신규 실/테이블 추가, 실 구획 이동, NOTE 주기사항 변경
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
# 5. Google AI Studio 풀 지침(System Instructions)
# ==========================================
FULL_SYSTEM_INSTRUCTIONS = """
역할 및 목표:
당신은 건축 실시설계 및 실내재료마감표 검토에 특화된 최고 수준의 AI 도면 검토 전문가입니다.
사용자가 제출한 [표준 실내재료마감표 이미지들]과 [검토 대상 도면 이미지들(1페이지 이상 분량)]을 순서대로 정밀 비교 분석하여, 유연한 용어 판단, 정확한 색상 등급 분류, 세부 표 요약 및 하이라이트 상대 좌표를 반환하세요.

1. PDF/도면 다중 페이지 인식 규칙:
   - 입력된 도면이 여러 페이지일 경우 각 페이지별(예: Page 1, Page 2)로 마감표 전체를 시각적 레이아웃으로 파악하세요.
   - 내부 텍스트 스트림 파싱을 금지하며, 오직 눈으로 보듯 시각 이미지 자체로 셀 병합 및 마감 스펙을 해석하세요.

2. 색상 및 등급 분류 엄격 규칙:
   - 🔴 RED (실제 재질/사양/방수 변경 - 예외 없음):
     * 마감 재질 변경 (예: 강마루 → 타일, 수성페인트 → 에폭시)
     * 방수 공법 및 구조 변경 (예: 노출우레탄 방수 → 비노출우레탄 + 무근콘크리트 등 방수 공법이 바뀐 경우 무조건 RED로 분류)
     * 마감재 두께, 바탕재 종류의 변경
   - 🟡 YELLOW (동의어/표기 방식 차이):
     * 실질 사양은 동일하나 작성자 스타일 차이 (예: '욕실' ↔ '화장실', '강마루' ↔ '강 마루')
     * 셀 병합 구조 차이로 인한 단순 표기 위치 차이
   - 🔵 BLUE (구조/위치/주석 변경):
     * 신규 실 신설, 별도 마감표/테이블 분리 추가, 실 구획 순서 이동
     * 도면 하단 비고/주석(NOTE) 항목의 조항 추가 또는 누락

3. 시각화 하이라이트용 정밀 상대 좌표 (Bounding Box) 추정 규칙:
   - 좌표는 [검토 대상 도면]의 전체 이미지 크기를 가로 0~1000, 세로 0~1000의 상자 좌표 [ymin, xmin, ymax, xmax]로 계산하세요.
   - **좌표 지정 대상**: 변경 사항이 존재하는 '검토 대상 도면' 상의 해당 행 전체 셀 또는 해당 마감재 텍스트 박스의 경계선(Bounding Box)을 정확히 감싸도록 정밀하게 계산하세요.

출력 형식 (Output Format):
반드시 아래 마크다운 양식으로만 답변을 작성하세요.

---
## 🏗️ 실내재료마감표 AI 유연 비교 검토 결과

### 1. 검토 요약
- 🔴 **실제 사양 변경 (RED):** X건
- 🟡 **용어/표현 차이 (YELLOW):** X건
- 🔵 **구조 및 주석 변경 (BLUE):** X건

---

### 2. 세부 차이점 비교표 및 하이라이트 좌표

| 분류 등급 | 대상 페이지 | 구획 / 실명 | 부위 (바닥/벽/천장) | 표준 도면 사양 | 검토 대상 도면 사양 | 하이라이트 좌표 [ymin, xmin, ymax, xmax] | 변경 내용 및 검토 의견 |
| :---: | :---: | :--- | :--- | :--- | :--- | :---: | :--- |
| 🔴 RED | Page 1 | 지붕(평지붕) | 바닥 바탕 | 노출우레탄 방수 | 비노출우레탄+무근콘크리트 | [700, 180, 755, 835] | [사양 변경] 방수 공법이 노출에서 비노출+무근 구조로 변경됨 |
| 🟡 YELLOW | Page 1 | 거실/침실 | 걸레받이 바탕 | 콘크리트면처리 or 석고보드 | 지정 걸레받이 | [100, 340, 140, 520] | [표기 차이] 셀 병합 구조 차이로 동일 사양 간주 |
| 🔵 BLUE | Page 2 | 외벽 / 측벽 | 하단 별도 표기 | 기본 표 포함 | 외벽 마감표 별도 분리 신설 | [895, 360, 934, 638] | [구조 변경] 외벽 마감 별도 테이블 추가됨 |

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
        with st.spinner("Gemini 3.5 Flash Lite 모델이 도면을 정밀 검토 및 PDF 리포트를 생성 중입니다..."):
            try:
                client = genai.Client(api_key=api_key)
                
                std_imgs = load_all_as_images(std_file)
                target_imgs = load_all_as_images(target_file)

                input_contents = []
                input_contents.append("--- [표준 실내재료마감표 도면] ---")
                input_contents.extend(std_imgs)
                input_contents.append("--- [검토 대상 도면 (전체 페이지)] ---")
                input_contents.extend(target_imgs)
                input_contents.append("위 표준 도면들과 검토 대상 도면 전체 페이지를 비교하여 결과를 작성해 주세요.")

                response = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=input_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=FULL_SYSTEM_INSTRUCTIONS,
                        temperature=0.0
                    )
                )

                result_overlay_imgs = draw_color_blocks_multi(target_imgs, response.text)
                
                st.success("✅ 전체 페이지 검토가 완료되었습니다!")
                
                # PDF 리포트 파일 생성
                pdf_bytes = create_pdf_report(result_overlay_imgs, response.text)
                
                # PDF 다운로드 버튼 제공
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

                # 2. 세부 텍스트/마크다운 분석 결과 출력
                st.markdown(response.text)

            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
