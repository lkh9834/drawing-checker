import io
import json
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image
from pdf2image import convert_from_bytes

# ==========================================
# 1. 페이지 기본 설정 및 디자인
# ==========================================
st.set_page_config(
    page_title="포레나 실내재료마감표 AI 비교 검토 시스템 ver0.1",
    layout="wide"
)

st.title("🏗️ 포레나 실내재료마감표 AI 비교 검토 시스템 ver0.1")
st.write("표준 도면 이미지/PDF와 검토 대상 도면(PDF/이미지)을 업로드하면, AI(Gemini 3.5 Flash Lite)가 시각 및 문맥 기반으로 초고속 비교 분석합니다.")

# ==========================================
# 2. 파일 변환 헬퍼 함수 (PDF / 이미지 통합 처리)
# ==========================================
def load_as_image(uploaded_file):
    """PDF 또는 이미지 파일을 PIL Image 객체로 안전하게 변환합니다."""
    file_bytes = uploaded_file.read()
    if uploaded_file.name.lower().endswith(".pdf"):
        # PDF 파일인 경우 첫 번째 페이지를 이미지(300 DPI)로 렌더링
        images = convert_from_bytes(file_bytes, dpi=300)
        return images[0]
    else:
        # 일반 이미지 파일인 경우
        return Image.open(io.BytesIO(file_bytes))

# ==========================================
# 3. 사이드바 - API Key 및 검토 안내
# ==========================================
with st.sidebar:
    st.header("🔑 설정")
    api_key = st.text_input("Google API Key를 입력하세요", type="password")
    st.markdown("[API Key 발급받기](https://aistudio.google.com/app/apikey)")
    st.divider()
    st.markdown("""
    **🎨 색상 등급 안내**
    - 🔴 **RED**: 실제 마감재 재질/사양 변경
    - 🟡 **YELLOW**: 동의어 및 표기 방식 차이
    - 🔵 **BLUE**: 구조/위치 및 주석(NOTE) 변경
    """)

# ==========================================
# 4. 도면 파일 업로드 구역
# ==========================================
col1, col2 = st.columns(2)
with col1:
    std_file = st.file_uploader("1. 표준 실내재료마감표 (이미지/PDF)", type=["png", "jpg", "jpeg", "pdf"])
with col2:
    target_file = st.file_uploader("2. 검토 대상 도면 (PDF/이미지)", type=["png", "jpg", "jpeg", "pdf"])

# ==========================================
# 5. Google AI Studio 풀 지침(System Instructions)
# ==========================================
FULL_SYSTEM_INSTRUCTIONS = """
역할 및 목표:
당신은 건축 실시설계 및 실내재료마감표 검토에 특화된 최고 수준의 AI 도면 검토 전문가입니다.
사용자가 첨부한 [이미지 1: 표준 실내재료마감표]와 [이미지 2 또는 PDF: 검토 대상 도면]을 시각적으로 비교 분석하여, 유연한 용어 판단, 색상별 차이점 요약, 그리고 외부 프로그램이 하이라이트 박스 오버레이를 그릴 수 있는 상대 좌표 데이터를 함께 반환하세요.

1. PDF/도면 인식 방식 (시각 인식 강제 규칙):
   - 첨부 파일이 PDF 형식이더라도 내부 텍스트(Text Layer) 스트림을 추출하여 파싱하지 마세요.
   - 도면 전체를 고해상도 시각 이미지(Visual Image)로만 간주하고, 사람의 눈으로 표를 보듯 표의 실선, 셀 병합 상태, 행/열 배치를 시각적으로 인식하세요.
   - 셀 병합으로 인해 여러 행에 걸쳐 있는 마감재 문구(예: '콘크리트면처리 or 시멘트몰탈 or 석고보드')는 병합된 구역 전체 실에 동일 적용된 것으로 해석하세요.

2. 유연한 문맥 검토 원칙 (Semantic Matching):
   - 작성자/협력사 스타일 차이에 따른 동의어는 정상(Match) 처리합니다.
     * 공간명: '욕실' ↔ '화장실', '주방 및 식당' ↔ '주방/식당', 'ELEV.홀' ↔ '승강기홀' 등
     * 마감재: '강마루' ↔ '강 마루', '수성페인트' ↔ '수성 도장', '액체방수' ↔ '시멘트액체방수' 등
   - 단순 띄어쓰기, 오탈자, 표의 행/열 배치 양식 차이는 사양 변경으로 처리하지 않습니다.

3. 차이점 색상 및 등급 분류 기준:
   - 🔴 RED (실제 재질/사양 변경): 마감재의 재질, 두께, 방수 스펙 자체가 변경된 경우 (예: 지정 타일 → 강마루, 수성페인트 → 에폭시)
   - 🟡 YELLOW (동의어/표기 방식 차이): 실질 사양은 동일하나 작성자 스타일 차이 및 셀 병합 영역 해석 차이
   - 🔵 BLUE (구조/위치/주석 변경): 실 구획 이동, 독립 행 분리, 또는 (최상층 천정) 등 비고/주석(NOTE) 조건 변경

4. 시각화 하이라이트용 상대 좌표 (Bounding Box) 반환 규칙:
   - [이미지 2/검토 도면] 기준으로 차이점이 발견된 구역의 상대 좌표 [ymin, xmin, ymax, xmax] (0~1000 정수 스케일)를 필수 계산하여 제공하세요.

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

| 분류 등급 | 구획 / 실명 | 부위 (바닥/벽/천장) | 표준 도면 사양 | 검토 대상 도면 사양 | 하이라이트 좌표 [ymin, xmin, ymax, xmax] | 변경 내용 및 검토 의견 |
| :---: | :--- | :--- | :--- | :--- | :---: | :--- |
| 🔴 RED | 실외기실 | 천장 비고 | (최상층 천정) 단열재 포함 | (최상층 천정) 조건 누락 | [240, 600, 280, 850] | [사양 변경] 최상층 단열재 조건 누락 확인 필요 |
| 🟡 YELLOW | 거실/침실 | 걸레받이 바탕 | 콘크리트면처리 or 시멘트몰탈 or 석고보드 | 지정 걸레받이 | [100, 340, 140, 520] | [표기 차이] 셀 병합 구조 차이로 동일 사양 간주 |
| 🔵 BLUE | 발코니 | 벽체/천장 | 콘크리트면처리 or CRC보드 | 단열재+석고보드+수성페인트 | [300, 330, 350, 830] | [주석 변경] 최상층 조건부 표기 위치 조정 |

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
        with st.spinner("Gemini 3.5 Flash Lite 모델이 두 도면을 초고속으로 유연 비교 분석 중입니다..."):
            try:
                # API 클라이언트 초기화
                client = genai.Client(api_key=api_key)
                
                # PDF/이미지 안전 자동 변환
                std_img = load_as_image(std_file)
                target_img = load_as_image(target_file)

                # 프롬프트 구성
                user_prompt = "첨부된 두 도면을 시스템 인스트럭션 규칙에 따라 유연하게 비교 분석하여 최종 검토 결과를 출력해 주세요."

                # Gemini 3.5 Flash Lite 모델 호출
                response = client.models.generate_content(
                    model="gemini-3.5-flash-lite",  # 👈 캡처 화면의 정확한 ID 문자열 적용
                    contents=[std_img, target_img, user_prompt],
                    config=types.GenerateContentConfig(
                        system_instruction=FULL_SYSTEM_INSTRUCTIONS,
                        temperature=0.2
                    )
                )

                # 결과 화면 출력
                st.success("✅ 검토가 성공적으로 완료되었습니다!")
                st.markdown(response.text)

            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
