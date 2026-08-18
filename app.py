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
        all_rows = []
        
        # قراءة كل الجداول من كافة صفحات الـ PDF
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        # تصفية الصفوف والتأكد من وجود بيانات
                        clean_row = [str(cell).strip().replace('\n', ' ') for cell in row if cell is not None and str(cell).strip() != '']
                        if len(clean_row) >= 3: # يتجاهل الصفوف الفارغة أو الضبابية
                            all_rows.append(clean_row)

        if len(all_rows) > 1:
            # تحويل البيانات القادمة بغض النظر عن عدد الأعمدة
            max_cols = max(len(r) for r in all_rows)
            headers = [f"عمود {i+1}" for i in range(max_cols)]
            
            # محاولة تسمية أهم الأعمدة
            if max_cols >= 4:
                headers[0] = "التاريخ"
                headers[1] = "البيان / الوصف"
                headers[-2] = "المدين (صادر)"
                headers[-1] = "الدائن (وارد)"

            df = pd.DataFrame(all_rows[1:], columns=headers[:max_cols])

            # معالجة وتنظيف الأرقام
            for col in df.columns:
                if "صادر" in col or "وارد" in col or "مبلغ" in col:
                    df[col] = pd.to_numeric(df[col].str.replace(',', ''), errors='coerce').fillna(0)

            st.success("تم تحليل الكشف واستخراج الجداول بنجاح! 🎉")

            tab1, tab2 = st.tabs(["📋 الكشف المفرغ (Data)", "📈 ملخص العمليات"])

            with tab1:
                st.dataframe(df, use_container_width=True)
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 تصدير إلى Excel (CSV)", csv, "Bank_Analysis.csv", "text/csv")

            with tab2:
                st.write("### إحصائيات عامة")
                st.metric("إجمالي عدد العمليات المستخرجة", len(df))
                st.dataframe(df.describe(include='all').fillna(''), use_container_width=True)
        else:
            st.error("لم يتم العثور على جداول واضحة داخل ملف PDF، يرجى التأكد من أن الملف يحتوي على كشف رقمي أو صورة ممسوحة جيدة.")
