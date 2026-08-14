import io
import re
import json
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image

# PDF 생성 관련 라이브러리 (텍스트 리포트 전용)
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ==========================================
# 1. 페이지 기본 설정 및 디자인
# ==========================================
st.set_page_config(
    page_title="실내재료마감표 AI 유연 비교 검토 시스템2",
    layout="wide"
)

st.title("🏗️ 실내재료마감표 AI 유연 비교 검토 시스템")
st.write("표준 도면과 검토 대상 도면의 **실별 마감재 스펙 및 하단 노트(NOTE) 주기사항**을 공간명 기준으로 전수 교차 분석하여 정밀 검토 리포트를 생성합니다.")

# ==========================================
# 2. PDF/이미지 처리 및 PDF 리포트 생성 함수
# ==========================================
def load_as_bytes(uploaded_file):
    """업로드된 파일의 바이트 및 이미지 데이터를 안전하게 읽어옵니다."""
    file_bytes = uploaded_file.read()
    if uploaded_file.name.lower().endswith(".pdf"):
        return {"data": file_bytes, "mime": "application/pdf"}
    else:
        img = Image.open(io.BytesIO(file_bytes))
        return {"data": img, "mime": "image/png"}

def create_pdf_report(result_text):
    """AI 검토 결과 마크다운 텍스트를 바탕으로 깔끔한 PDF 보고서를 메모리 상에서 생성합니다."""
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=35, leftMargin=35, topMargin=35, bottomMargin=35)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#1E3A8A'))
    h2_style = ParagraphStyle('H2Style', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#1F2937'))
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontSize=9, leading=13)
    
    # 1. 보고서 제목
    story.append(Paragraph("<b>[AI Document Review] 실내재료마감표 검토 보고서</b>", title_style))
    story.append(Spacer(1, 15))
    
    # 2. 마크다운 검토 텍스트 정제 및 PDF 변환
    clean_lines = result_text.split('\n')
    for line in clean_lines:
        line_str = line.strip()
        if not line_str:
            story.append(Spacer(1, 3))
            continue
            
        if line_str.startswith("## "):
            story.append(Spacer(1, 8))
            story.append(Paragraph(f"<b>{line_str.replace('##', '').strip()}</b>", h2_style))
            story.append(Spacer(1, 4))
        elif line_str.startswith("### "):
            story.append(Spacer(1, 6))
            story.append(Paragraph(f"<b>{line_str.replace('###', '').strip()}</b>", h2_style))
            story.append(Spacer(1, 3))
        elif line_str.startswith("-"):
            text_content = line_str[1:].strip().replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(f"• {text_content}", normal_style))
            story.append(Spacer(1, 2))
        elif "|" in line_str:
            cells = [c.strip() for c in line_str.split('|')[1:-1]]
            if len(cells) >= 4 and not all(c.startswith(':-') or c.startswith('-') for c in cells):
                table_row = " | ".join(cells).replace('<', '&lt;').replace('>', '&gt;')
                story.append(Paragraph(f"<font size=8>{table_row}</font>", normal_style))
                story.append(Spacer(1, 2))
        else:
            text_content = line_str.replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(text_content, normal_style))
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
    **🎨 색상 등급 분류 정렬 순서**
    - 🔴 **RED (1순위 - 사양 변경)**: 재질/방수/NOTE 스펙 변경
    - 🟡 **YELLOW (2순위 - 표기 차이)**: 용어/동의어 및 표기 양식 차이
    - 🔵 **BLUE (3순위 - 구조/신설)**: 신규 실/테이블 추가, 순서 변경
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
# 5. Google AI Studio 엄격 지침(System Instructions)
# ==========================================
FULL_SYSTEM_INSTRUCTIONS = """
역할 및 목표:
당신은 건축 실시설계 도면 검토 전문가입니다.
[표준 도면]과 [검토 대상 도면]의 마감표 본문과 하단 노트(NOTE/주기사항) 영역을 교차 검증하여 정밀 분석하세요.

1. 세부 차이점 비교표 정렬 규칙 (★필수 준수):
   - **비교표의 행(Row) 출력 순서는 반드시 분류 등급 우선순위에 따라 정렬하세요.**
   - **1순위**: 🔴 RED (실제 사양/방수/노트 변경) 항목 전체
   - **2순위**: 🟡 YELLOW (동의어/표기 방식 차이) 항목 전체
   - **3순위**: 🔵 BLUE (구조/신설/배치 변경) 항목 전체

2. '부위' 열(Column) 작성 표준화 규칙 (★필수 준수):
   '부위' 열에는 임의의 혼합 명칭(예: '벽 바탕/마감', '바닥/걸레받이')을 사용해서는 안 되며, **반드시 아래 9가지 명칭 중 단 하나만 선택**하여 작성하세요:
   - `바닥 바탕`
   - `바닥 마감`
   - `걸레받이 바탕`
   - `걸레받이 마감`
   - `벽 바탕`
   - `벽 마감`
   - `천장 바탕`
   - `천장 마감`
   - `노트(NOTE)` (도면 하단 주기사항인 경우)

3. 도면 노트(NOTE / 범례 / 주기사항) 전수 검토 규칙:
   - 도면 하단에 작성된 주기사항(NOTE) 항목의 문구를 1:1로 정밀하게 비교하세요.
   - NOTE 조항의 추가, 삭제, 번호 변경, 주요 시방 스펙 변경(예: 방청페인트 제외, 시멘트몰탈 두께 변경 등)이 확인되면 반드시 결과표에 포함하세요.
   - 노트 변경 사항 작성 시:
     * 구획 / 실명: `도면 노트(NOTE)`
     * 부위: `노트(NOTE)`
     * 분류 등급: 주요 시방 조건 변경인 경우 🔴 RED, 단순 문구 정리/번호 이동인 경우 🔵 BLUE

4. 교차 매칭(Cross-Matching) 원칙:
   - 표의 행 순서가 서로 달라도 동일한 실명(공간명)을 찾아 1:1로 스펙을 비교하세요.
   - 검토 대상 도면에만 새로 신설된 실/테이블은 🔵 BLUE (구조/신설)로 처리하세요.

5. 색상 및 등급 분류 기준:
   - 🔴 RED (실제 재질/사양/방수/노트 변경):
     * 마감 재질, 바탕재, 두께, 도장 변경
     * **방수 공법 변경 (예: 노출우레탄 방수 → 비노출우레탄 + 무근콘크리트)은 무조건 RED**
     * **NOTE 주기사항의 중요 조건 변경/누락**
   - 🟡 YELLOW (동의어/표기 방식 차이):
     * 실질 사양은 동일하나 용어 차이 ('욕실' ↔ '화장실') 및 셀 병합에 따른 표기 위치 차이
   - 🔵 BLUE (구조/신설/배치 변경):
     * 신규 실 신설, 별도 마감표 분리 신설, 표의 행 순서 변경

출력 형식 (Output Format):
반드시 아래 마크다운 양식으로만 답변을 작성하세요.

---
## 🏗️ 실내재료마감표 AI 유연 비교 검토 결과

### 1. 검토 요약
- 🔴 **실제 사양 변경 (RED):** X건
- 🟡 **용어/표현 차이 (YELLOW):** X건
- 🔵 **구조 및 주석 변경 (BLUE):** X건

---

### 2. 세부 차이점 비교표

| 분류 등급 | 대상 페이지 | 구획 / 실명 | 부위 | 표준 도면 사양 | 검토 대상 도면 사양 | 변경 내용 및 검토 의견 |
| :---: | :---: | :--- | :--- | :--- | :--- | :--- |
| 🔴 RED | Page 1 | 지붕(평지붕) | 바닥 바탕 | 노출우레탄 방수 | 비노출우레탄+무근콘크리트 | [사양 변경] 방수 공법 변경됨 |
| 🔴 RED | Page 1 | 도면 노트(NOTE) | 노트(NOTE) | NOTE 17. 광명단 제외 | NOTE 17. 조항 삭제됨 | [노트 변경] 방청페인트 관련 주석 삭제 확인 필요 |
| 🟡 YELLOW | Page 1 | 거실/침실 | 걸레받이 바탕 | 콘크리트면처리 or 석고보드 | 지정 걸레받이 | [표기 차이] 셀 병합 양식 차이 |
| 🔵 BLUE | Page 2 | 외벽 / 측벽 | 벽 마감 | 기본 표 포함 | 외벽 마감표 별도 분리 신설 | [구조 변경] 별도 테이블 추가 신설 |

---

### 3. 검토 총평 및 조치 권고사항
(전체적인 마감재 및 NOTE 조항 변경 경향을 2~3줄로 요약 작성)
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
        with st.spinner("Gemini 3.5 Flash Lite 모델이 분류 등급순(RED ➔ YELLOW ➔ BLUE)으로 정밀 검토 중입니다..."):
            try:
                client = genai.Client(api_key=api_key)
                
                std_data = load_as_bytes(std_file)
                target_data = load_as_bytes(target_file)

                input_contents = []
                input_contents.append("--- [표준 실내재료마감표 도면] ---")
                input_contents.append(std_data["data"])
                input_contents.append("--- [검토 대상 도면] ---")
                input_contents.append(target_data["data"])
                input_contents.append("지시된 9가지 '부위' 표준 명칭을 사용하고, 비교표 결과는 반드시 분류 등급(RED -> YELLOW -> BLUE) 순서대로 정렬하여 작성해 주세요.")

                response = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=input_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=FULL_SYSTEM_INSTRUCTIONS,
                        temperature=0.0
                    )
                )
                
                st.success("✅ 분류 등급 정렬 검토가 완료되었습니다!")
                
                # PDF 리포트 생성 및 다운로드 버튼
                pdf_bytes = create_pdf_report(response.text)
                st.download_button(
                    label="📄 검토 결과 PDF 보고서 다운로드",
                    data=pdf_bytes,
                    file_name="실내재료마감표_AI_검토보고서.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
                
                st.divider()

                # 화면에 검토 마크다운 세부 비교표 출력
                st.markdown(response.text)

            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
