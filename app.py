import streamlit as st
import pandas as pd
import pdfplumber
import io
import re

st.set_page_config(page_title="المحلل المالي الذكي", layout="centered")

# ============================================================
# محاولة استيراد مكتبات تشكيل النص العربي (اختيارية)
# pip install arabic-reshaper python-bidi
# ============================================================
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    ARABIC_LIBS_AVAILABLE = True
except ImportError:
    ARABIC_LIBS_AVAILABLE = False


def fix_arabic_display(text):
    """يستخدم فقط لو المستخدم فعّل الخيار ومكتبات التشكيل متاحة."""
    if not isinstance(text, str) or not ARABIC_LIBS_AVAILABLE:
        return text
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text


def reverse_arabic_words(text):
    """عكس ترتيب الأحرف داخل كل كلمة عربية فقط (خيار احتياطي يدوي)."""
    if not isinstance(text, str):
        return text
    return re.sub(r'[\u0600-\u06FF]+', lambda m: m.group(0)[::-1], text)


def clean_amount(value):
    """تحويل نص المبلغ إلى رقم فعلي (يزيل الفواصل، العملة، المسافات)."""
    if value is None:
        return None
    s = str(value).strip()
    if s == '' or s.lower() in ('nan', 'none', '-'):
        return None
    # إزالة أي شيء ليس رقمًا أو فاصلة عشرية أو إشارة سالب
    s = s.replace(',', '').replace('٬', '')
    s = re.sub(r'[^\d\.\-]', '', s)
    if s in ('', '-', '.'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def guess_column(columns, keywords):
    """يحاول إيجاد اسم العمود الأقرب لمجموعة كلمات مفتاحية."""
    for col in columns:
        col_norm = str(col).strip()
        for kw in keywords:
            if kw in col_norm:
                return col
    return None


def extract_via_tables(pdf):
    raw_rows = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            for row in table:
                clean_row = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in row]
                if any(cell != '' for cell in clean_row):
                    raw_rows.append(clean_row)
    return raw_rows


def extract_via_text(pdf):
    """خطة بديلة: تقسيم الأسطر بناءً على تجمعات مسافات (لكشوفات بدون خطوط جدول)."""
    raw_rows = []
    for page in pdf.pages:
        text = page.extract_text() or ''
        for line in text.split('\n'):
            # تقسيم عند وجود مسافتين أو أكثر (عمود منفصل عن الآخر)
            parts = re.split(r'\s{2,}', line.strip())
            parts = [p for p in parts if p != '']
            if len(parts) >= 3:
                raw_rows.append(parts)
    return raw_rows


st.title("📊 المحلل المالي الذكي")
st.write("أتمتة تفريغ وتحليل الكشوفات البنكية")
st.write("---")

with st.expander("⚙️ إعدادات متقدمة"):
    apply_reversal = st.checkbox(
        "عكس ترتيب أحرف الكلمات العربية (فعّله فقط لو النص يظهر مقلوبًا)",
        value=False
    )
    use_reshape = st.checkbox(
        "استخدام تشكيل النص العربي (arabic-reshaper) إن كان متاحًا",
        value=False,
        disabled=not ARABIC_LIBS_AVAILABLE,
        help="ثبّت المكتبتين بالأمر: pip install arabic-reshaper python-bidi" if not ARABIC_LIBS_AVAILABLE else None
    )

uploaded_file = st.file_uploader("قم برفع كشف الحساب (PDF)", type=["pdf"])

if uploaded_file is not None:
    with st.spinner("جاري تحليل الكشف..."):
        with pdfplumber.open(uploaded_file) as pdf:
            raw_data = extract_via_tables(pdf)
            extraction_method = "جداول PDF (extract_tables)"
            if len(raw_data) < 2:
                # خطة بديلة إذا لم توجد جداول واضحة
                pdf_text_pages = pdf.pages
                raw_data = extract_via_text(pdf)
                extraction_method = "استخراج نصي احتياطي (extract_text)"

        if len(raw_data) < 2:
            st.error(
                "لم يتم العثور على بيانات واضحة داخل ملف PDF. "
                "قد يكون الملف عبارة عن صورة ممسوحة ضوئيًا ويحتاج OCR."
            )
        else:
            def process_cell(cell):
                if apply_reversal:
                    cell = reverse_arabic_words(cell)
                if use_reshape:
                    cell = fix_arabic_display(cell)
                return cell

            headers = [process_cell(h) for h in raw_data[0]]
            # توحيد طول الصفوف مع طول الترويسة
            n_cols = len(headers)
            body_rows = []
            for row in raw_data[1:]:
                row = [process_cell(c) for c in row]
                if len(row) < n_cols:
                    row += [''] * (n_cols - len(row))
                elif len(row) > n_cols:
                    row = row[:n_cols]
                body_rows.append(row)

            df = pd.DataFrame(body_rows, columns=headers)
            # إزالة الصفوف التي تكرر الترويسة نفسها
            df = df[~df.apply(lambda r: list(r) == list(headers), axis=1)]
            df = df.reset_index(drop=True)

            st.success(f"تم تحليل الكشف بنجاح! ({len(df)} عملية) — طريقة الاستخراج: {extraction_method}")

            tab1, tab2 = st.tabs(["📋 الكشف المفرغ", "📈 ملخص التحليل المالي"])

            with tab1:
                st.dataframe(df, use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Bank_Report')
                excel_data = output.getvalue()

                st.download_button(
                    label="📥 تصدير إلى Excel (.xlsx)",
                    data=excel_data,
                    file_name="Bank_Analysis_Report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            with tab2:
                st.write("### تحديد الأعمدة المالية")
                cols = list(df.columns)

                credit_guess = guess_column(cols, ['دائن', 'ايداع', 'إيداع', 'credit'])
                debit_guess = guess_column(cols, ['مدين', 'سحب', 'debit'])
                balance_guess = guess_column(cols, ['رصيد', 'balance'])
                date_guess = guess_column(cols, ['تاريخ', 'date'])

                c1, c2 = st.columns(2)
                with c1:
                    credit_col = st.selectbox(
                        "عمود الدائن / الإيداع", ['-- لا يوجد --'] + cols,
                        index=(cols.index(credit_guess) + 1) if credit_guess in cols else 0
                    )
                    balance_col = st.selectbox(
                        "عمود الرصيد", ['-- لا يوجد --'] + cols,
                        index=(cols.index(balance_guess) + 1) if balance_guess in cols else 0
                    )
                with c2:
                    debit_col = st.selectbox(
                        "عمود المدين / السحب", ['-- لا يوجد --'] + cols,
                        index=(cols.index(debit_guess) + 1) if debit_guess in cols else 0
                    )
                    date_col = st.selectbox(
                        "عمود التاريخ (اختياري، لرسم بياني)", ['-- لا يوجد --'] + cols,
                        index=(cols.index(date_guess) + 1) if date_guess in cols else 0
                    )

                st.write("---")
                st.write("### إحصائيات عامة")

                total_credit = total_debit = None

                m1, m2, m3 = st.columns(3)
                m1.metric("إجمالي عدد العمليات", len(df))

                if credit_col != '-- لا يوجد --':
                    total_credit = df[credit_col].apply(clean_amount).sum()
                    m2.metric("إجمالي الدائن / الإيداعات", f"{total_credit:,.2f}")

                if debit_col != '-- لا يوجد --':
                    total_debit = df[debit_col].apply(clean_amount).sum()
                    m3.metric("إجمالي المدين / السحوبات", f"{total_debit:,.2f}")

                if total_credit is not None and total_debit is not None:
                    net = total_credit - total_debit
                    st.metric("صافي الحركة (دائن - مدين)", f"{net:,.2f}")

                if balance_col != '-- لا يوجد --':
                    balances = df[balance_col].apply(clean_amount).dropna()
                    if not balances.empty:
                        st.write("### تطور الرصيد عبر العمليات")
                        st.line_chart(balances.reset_index(drop=True))
                        b1, b2 = st.columns(2)
                        b1.metric("أول رصيد مسجل", f"{balances.iloc[0]:,.2f}")
                        b2.metric("آخر رصيد مسجل", f"{balances.iloc[-1]:,.2f}")

                st.write("---")
                st.write("### أكبر 5 عمليات دائنة/مدينة")
                if credit_col != '-- لا يوجد --':
                    tmp = df.copy()
                    tmp['_val'] = tmp[credit_col].apply(clean_amount)
                    st.write("**أعلى إيداعات:**")
                    st.dataframe(tmp.sort_values('_val', ascending=False).head(5).drop(columns='_val'))
                if debit_col != '-- لا يوجد --':
                    tmp = df.copy()
                    tmp['_val'] = tmp[debit_col].apply(clean_amount)
                    st.write("**أعلى سحوبات:**")
                    st.dataframe(tmp.sort_values('_val', ascending=False).head(5).drop(columns='_val'))
