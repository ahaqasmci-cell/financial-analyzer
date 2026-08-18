import streamlit as st
import pandas as pd
import pdfplumber

st.set_page_config(page_title="المحلل المالي الذكي", layout="centered")

st.title("📊 المحلل المالي الذكي")
st.write("أتمتة تفريغ وتحليل الكشوفات البنكية بالذكاء الاصطناعي")
st.write("---")

uploaded_file = st.file_uploader("قم برفع كشف الحساب (PDF)", type=["pdf"])

if uploaded_file is not None:
    with st.spinner("جاري تحليل البيانات..."):
        transactions = []
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table:
                    for row in table[1:]:
                        if len(row) >= 4:
                            transactions.append(row)

        df = pd.DataFrame(transactions, columns=["التاريخ", "البيان", "المدين (صادر)", "الدائن (وارد)"])
        df["المدين (صادر)"] = pd.to_numeric(df["المدين (صادر)"].str.replace(',', ''), errors='coerce').fillna(0)
        df["الدائن (وارد)"] = pd.to_numeric(df["الدائن (وارد)"].str.replace(',', ''), errors='coerce').fillna(0)

        def classify_type(row):
            text = str(row["البيان"])
            if row["الدائن (وارد)"] > 0:
                if "نقدي" in text: return "إيداع نقدي"
                elif "شيك" in text: return "شيك وارد"
                else: return "حوالة واردة"
            else: return "حوالة صادرة / مصروفات"

        df["نوع العملية"] = df.apply(classify_type, axis=1)

        def extract_entity(text):
            text = str(text)
            for prefix in ["شركة ", "مؤسسة ", "فرع "]:
                if prefix in text:
                    return prefix + text.split(prefix)[1].split("-")[0].strip()
            return "جهات عامة / أخرى"

        df["المتعامل"] = df["البيان"].apply(extract_entity)

    st.success("تم التحليل بنجاح! 🎉")

    tab1, tab2, tab3 = st.tabs(["📋 الكشف (Excel)", "📈 التحليل", "👥 المتعاملين"])

    with tab1:
        st.dataframe(df)
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 تصدير ملف CSV", csv, "Bank_Analysis.csv", "text/csv")

    with tab2:
        total_in = df["الدائن (وارد)"].sum()
        total_out = df["المدين (صادر)"].sum()
        st.metric("إجمالي الوارد", f"{total_in:,.2f} ر.س")
        st.metric("إجمالي الصادر", f"{total_out:,.2f} ر.س")
        st.write("---")
        st.write("### توزيع الإيداعات")
        deposits_df = df[df["الدائن (وارد)"] > 0].groupby("نوع العملية")["الدائن (وارد)"].sum()
        st.bar_chart(deposits_df)

    with tab3:
        entities = df.groupby("المتعامل").agg(
            عدد_العمليات=("التاريخ", "count"),
            إجمالي_الوارد=("الدائن (وارد)", "sum"),
            إجمالي_الصادر=("المدين (صادر)", "sum")
        ).reset_index()
        st.dataframe(entities)
