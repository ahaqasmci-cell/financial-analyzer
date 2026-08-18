import streamlit as st
import pandas as pd
import pdfplumber
import io

st.set_page_config(page_title="المحلل المالي الذكي", layout="centered")

st.title("📊 المحلل المالي الذكي")
st.write("أتمتة تفريغ وتحليل الكشوفات البنكية بالذكاء الاصطناعي")
st.write("---")

uploaded_file = st.file_uploader("قم برفع كشف الحساب (PDF)", type=["pdf"])

if uploaded_file is not None:
    with st.spinner("جاري تحليل الكشف البنكي وتنسيق البيانات..."):
        raw_data = []
        
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        clean_row = [str(cell).strip().replace('\n', ' ') for cell in row if cell is not None and str(cell).strip() != '']
                        if len(clean_row) >= 3:
                            raw_data.append(clean_row)

        if len(raw_data) > 1:
            # استخدام الصف الأول من الكشف نفسه كعناوين للأعمدة لضمان تطابق البيانات تماماً
            headers = raw_data[0]
            df = pd.DataFrame(raw_data[1:], columns=headers)

            # تنظيف أي صفوف مكررة تحتوي على العناوين داخل الجداول
            df = df[~df.isin(headers).all(axis=1)]

            st.success("تم تحليل الكشف واستخراج الجداول بنجاح! 🎉")

            tab1, tab2 = st.tabs(["📋 الكشف المفرغ (Data)", "📈 ملخص العمليات"])

            with tab1:
                st.dataframe(df, use_container_width=True)
                
                # تصدير إكسل حقيقي (.xlsx) متوافق 100% مع أجهزة الآيفون واللغة العربية
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='KSA_Bank_Report')
                excel_data = output.getvalue()
                
                st.download_button(
                    label="📥 تصدير إلى Excel (.xlsx)",
                    data=excel_data,
                    file_name="Bank_Analysis_Report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            with tab2:
                st.write("### إحصائيات عامة")
                st.metric("إجمالي عدد العمليات المستخرجة", len(df))
                st.dataframe(df, use_container_width=True)
        else:
            st.error("لم يتم العثور على جداول واضحة داخل ملف PDF.")
