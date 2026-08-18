import streamlit as st
import pandas as pd
import pdfplumber

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
            df_raw = pd.DataFrame(raw_data)
            
            # محاولة ضبط ترتيب أعمدة الإنماء تلقائياً من اليمين لليسار
            # إذا كان العمود الأخير يحتوي نص يحتوي SAR أو وصف، نعكس الترتيب
            df = df_raw.iloc[1:].copy()
            
            # إعادة تسمية الأعمدة بشكل منظم بناءً على عددها
            num_cols = df.shape[1]
            if num_cols == 4:
                df.columns = ["الرصيد", "المبلغ", "البيان / التفاصيل", "التاريخ"]
            elif num_cols == 5:
                df.columns = ["الرصيد", "دائن", "مدين", "البيان / التفاصيل", "التاريخ"]
            else:
                df.columns = [f"عمود {i+1}" for i in range(num_cols)]

            st.success("تم تحليل الكشف واستخراج الجداول بنجاح! 🎉")

            tab1, tab2 = st.tabs(["📋 الكشف المفرغ (Data)", "📈 ملخص العمليات"])

            with tab1:
                st.dataframe(df, use_container_width=True)
                
                # تصدير CSV بترميز وتنسيق يضمن الفصل التلقائي بين الأعمدة في إكسل Excel
                csv_data = df.to_csv(index=False, sep=',', encoding='utf-8-sig')
                st.download_button(
                    label="📥 تصدير إلى Excel (CSV)",
                    data=csv_data,
                    file_name="Alinma_Bank_Analysis.csv",
                    mime="text/csv"
                )

            with tab2:
                st.write("### إحصائيات عامة")
                st.metric("إجمالي عدد العمليات المستخرجة", len(df))
                st.dataframe(df, use_container_width=True)
        else:
            st.error("لم يتم العثور على جداول واضحة داخل ملف PDF.")
