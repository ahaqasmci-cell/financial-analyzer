import streamlit as st
import pandas as pd
import pdfplumber
import io
import re

st.set_page_config(page_title="المحلل المالي الذكي", layout="centered")

# ============================================================
# مكتبات تشكيل النص العربي (اختيارية)
# ============================================================
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    ARABIC_LIBS_AVAILABLE = True
except ImportError:
    ARABIC_LIBS_AVAILABLE = False


def fix_arabic_display(text):
    if not isinstance(text, str) or not ARABIC_LIBS_AVAILABLE:
        return text
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def reverse_arabic_words(text):
    if not isinstance(text, str):
        return text
    return re.sub(r'[\u0600-\u06FF]+', lambda m: m.group(0)[::-1], text)


def clean_amount(value):
    if value is None:
        return None
    s = str(value).strip()
    if s == '' or s.lower() in ('nan', 'none', '-'):
        return None
    s = s.replace(',', '').replace('٬', '')
    s = re.sub(r'[^\d\.\-]', '', s)
    if s in ('', '-', '.'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def suggest_header_name(raw_name):
    """يقترح اسم عمود عربي واضح بناءً على كلمات مفتاحية موجودة بالاسم الخام."""
    n = str(raw_name).lower()
    if 'balance' in n or 'رصيد' in raw_name:
        return 'الرصيد'
    if 'credit' in n or 'دائن' in raw_name:
        return 'دائن (إيداع)'
    if 'debit' in n or 'مدين' in raw_name:
        return 'مدين (سحب)'
    if 'date' in n or 'تاريخ' in raw_name:
        return 'التاريخ'
    if 'detail' in n or 'desc' in n or 'تفاصيل' in raw_name or 'بيان' in raw_name or 'وصف' in raw_name:
        return 'تفاصيل العملية'
    if 'ref' in n or 'مرجع' in raw_name:
        return 'رقم المرجع'
    return raw_name


def guess_column(columns, keywords):
    for col in columns:
        for kw in keywords:
            if kw in str(col):
                return col
    return None


def extract_via_tables(pdf):
    raw_rows = []
    for page in pdf.pages:
        for table in page.extract_tables():
            for row in table:
                clean_row = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in row]
                if any(cell != '' for cell in clean_row):
                    raw_rows.append(clean_row)
    return raw_rows


def extract_via_text(pdf):
    raw_rows = []
    for page in pdf.pages:
        text = page.extract_text() or ''
        for line in text.split('\n'):
            parts = [p for p in re.split(r'\s{2,}', line.strip()) if p != '']
            if len(parts) >= 3:
                raw_rows.append(parts)
    return raw_rows


# ============================================================
# استخراج اسم الطرف الآخر ونوع العملية من نص تفاصيل العملية
# ملاحظة: الصياغة تختلف من بنك لآخر، هذا اجتهاد عام قابل للتحسين
# ============================================================
METHOD_KEYWORDS = [
    ('شيك', 'شيك'),
    ('تحويل', 'تحويل'),
    ('حوالة', 'تحويل'),
    ('ايداع', 'إيداع نقدي'),
    ('إيداع', 'إيداع نقدي'),
    ('سحب', 'سحب نقدي'),
    ('رسوم', 'رسوم / عمولة'),
    ('عمولة', 'رسوم / عمولة'),
    ('فاتورة', 'دفع فاتورة'),
    ('purchase', 'شراء / نقاط بيع'),
    ('pos', 'شراء / نقاط بيع'),
]

NAME_PATTERNS = [
    r'(?:من العميل|من الاستاذ|من السيد|من)\s*[:\-]?\s*([\u0600-\u06FF\s]{3,40})',
    r'(?:الى العميل|إلى العميل|الى|إلى|لصالح|باسم)\s*[:\-]?\s*([\u0600-\u06FF\s]{3,40})',
]


def classify_method(description):
    if not isinstance(description, str):
        return 'غير محدد'
    d = description.lower()
    for kw, label in METHOD_KEYWORDS:
        if kw in description or kw in d:
            return label
    return 'أخرى'


def extract_party_name(description):
    if not isinstance(description, str) or description.strip() == '':
        return 'غير محدد'
    for pat in NAME_PATTERNS:
        m = re.search(pat, description)
        if m:
            name = m.group(1).strip()
            name = re.sub(r'\s{2,}', ' ', name)
            if len(name) >= 3:
                return name
    # لا يوجد اسم واضح -> استخدم النص كاملاً كمعرف للتجميع
    return description.strip()[:40]


st.title("📊 المحلل المالي الذكي")
st.write("أتمتة تفريغ وتحليل الكشوفات البنكية")
st.write("---")

with st.expander("⚙️ إعدادات متقدمة"):
    apply_reversal = st.checkbox("عكس ترتيب أحرف الكلمات العربية (فعّله فقط لو النص يظهر مقلوبًا)", value=False)
    use_reshape = st.checkbox(
        "استخدام تشكيل النص العربي (arabic-reshaper) إن كان متاحًا",
        value=False, disabled=not ARABIC_LIBS_AVAILABLE,
        help="ثبّت المكتبتين: pip install arabic-reshaper python-bidi" if not ARABIC_LIBS_AVAILABLE else None
    )

uploaded_file = st.file_uploader("قم برفع كشف الحساب (PDF)", type=["pdf"])

if uploaded_file is not None:
    with st.spinner("جاري تحليل الكشف..."):
        with pdfplumber.open(uploaded_file) as pdf:
            raw_data = extract_via_tables(pdf)
            extraction_method = "جداول PDF (extract_tables)"
            if len(raw_data) < 2:
                raw_data = extract_via_text(pdf)
                extraction_method = "استخراج نصي احتياطي (extract_text)"

        if len(raw_data) < 2:
            st.error("لم يتم العثور على بيانات واضحة داخل ملف PDF. قد يكون الملف صورة ممسوحة ضوئيًا وتحتاج OCR.")
        else:
            def process_cell(cell):
                if apply_reversal:
                    cell = reverse_arabic_words(cell)
                if use_reshape:
                    cell = fix_arabic_display(cell)
                return cell

            raw_headers = [process_cell(h) for h in raw_data[0]]
            n_cols = len(raw_headers)
            body_rows = []
            for row in raw_data[1:]:
                row = [process_cell(c) for c in row]
                if len(row) < n_cols:
                    row += [''] * (n_cols - len(row))
                elif len(row) > n_cols:
                    row = row[:n_cols]
                body_rows.append(row)

            df = pd.DataFrame(body_rows, columns=raw_headers)
            df = df[~df.apply(lambda r: list(r) == list(raw_headers), axis=1)].reset_index(drop=True)

            st.success(f"تم تحليل الكشف بنجاح! ({len(df)} عملية) — طريقة الاستخراج: {extraction_method}")

            # ---------- تصحيح أسماء الأعمدة يدويًا ----------
            st.write("### ✏️ تأكيد / تصحيح أسماء الأعمدة")
            st.caption("النص المستخرج من PDF أحيانًا يظهر بترتيب معكوس. راجع الأسماء المقترحة وعدّلها إذا لزم.")
            new_names = {}
            cols_per_row = 2
            raw_cols = list(df.columns)
            for i in range(0, len(raw_cols), cols_per_row):
                cols_ui = st.columns(cols_per_row)
                for j, orig in enumerate(raw_cols[i:i + cols_per_row]):
                    with cols_ui[j]:
                        suggested = suggest_header_name(orig)
                        new_names[orig] = st.text_input(f"العمود: `{orig}`", value=suggested, key=f"col_{i}_{j}")

            df = df.rename(columns=new_names)

            tab1, tab2 = st.tabs(["📋 الكشف المفرغ", "📈 ملخص التحليل المالي"])

            with tab1:
                st.dataframe(df, use_container_width=True)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Bank_Report')
                st.download_button(
                    "📥 تصدير إلى Excel (.xlsx)", data=output.getvalue(),
                    file_name="Bank_Analysis_Report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            with tab2:
                cols = list(df.columns)
                st.write("### تحديد الأعمدة")

                credit_guess = guess_column(cols, ['دائن', 'إيداع', 'ايداع', 'Credit'])
                debit_guess = guess_column(cols, ['مدين', 'سحب', 'Debit'])
                balance_guess = guess_column(cols, ['رصيد', 'Balance'])
                date_guess = guess_column(cols, ['تاريخ', 'Date'])
                detail_guess = guess_column(cols, ['تفاصيل', 'بيان', 'وصف', 'Detail', 'Desc'])

                c1, c2 = st.columns(2)
                with c1:
                    credit_col = st.selectbox("عمود الدائن / الإيداع", ['-- لا يوجد --'] + cols,
                                               index=(cols.index(credit_guess) + 1) if credit_guess in cols else 0)
                    balance_col = st.selectbox("عمود الرصيد", ['-- لا يوجد --'] + cols,
                                                index=(cols.index(balance_guess) + 1) if balance_guess in cols else 0)
                    detail_col = st.selectbox("عمود تفاصيل العملية", ['-- لا يوجد --'] + cols,
                                               index=(cols.index(detail_guess) + 1) if detail_guess in cols else 0)
                with c2:
                    debit_col = st.selectbox("عمود المدين / السحب", ['-- لا يوجد --'] + cols,
                                              index=(cols.index(debit_guess) + 1) if debit_guess in cols else 0)
                    date_col = st.selectbox("عمود التاريخ", ['-- لا يوجد --'] + cols,
                                             index=(cols.index(date_guess) + 1) if date_guess in cols else 0)

                st.write("---")
                st.write("### إحصائيات عامة")

                total_credit = total_debit = None
                m1, m2, m3 = st.columns(3)
                m1.metric("إجمالي عدد العمليات", len(df))
                if credit_col != '-- لا يوجد --':
                    total_credit = df[credit_col].apply(clean_amount).sum()
                    m2.metric("إجمالي الإيداعات", f"{total_credit:,.2f}")
                if debit_col != '-- لا يوجد --':
                    total_debit = df[debit_col].apply(clean_amount).sum()
                    m3.metric("إجمالي السحوبات", f"{total_debit:,.2f}")
                if total_credit is not None and total_debit is not None:
                    st.metric("صافي الحركة", f"{total_credit - total_debit:,.2f}")

                if balance_col != '-- لا يوجد --':
                    balances = df[balance_col].apply(clean_amount).dropna()
                    if not balances.empty:
                        st.write("### تطور الرصيد")
                        st.line_chart(balances.reset_index(drop=True))

                # ---------- تحليل تفاصيل العمليات (يحتاج عمود التفاصيل) ----------
                if detail_col != '-- لا يوجد --':
                    work = df.copy()
                    work['_credit'] = work[credit_col].apply(clean_amount) if credit_col != '-- لا يوجد --' else None
                    work['_debit'] = work[debit_col].apply(clean_amount) if debit_col != '-- لا يوجد --' else None
                    work['_method'] = work[detail_col].apply(classify_method)
                    work['_party'] = work[detail_col].apply(extract_party_name)

                    st.write("---")
                    st.write("### 🏦 أبرز المودعين (عمليات واردة)")
                    if credit_col != '-- لا يوجد --':
                        deposits = work[work['_credit'].fillna(0) > 0]
                        if not deposits.empty:
                            summary = deposits.groupby('_party').agg(
                                عدد_العمليات=('_credit', 'count'),
                                إجمالي_المبلغ=('_credit', 'sum'),
                                طرق_الدفع=('_method', lambda s: ', '.join(sorted(set(s))))
                            ).sort_values('إجمالي_المبلغ', ascending=False).reset_index()
                            summary.columns = ['الاسم / الجهة', 'عدد العمليات', 'إجمالي المبلغ', 'نوع العملية']
                            st.dataframe(summary.head(15), use_container_width=True)
                        else:
                            st.info("لا توجد عمليات إيداع في هذا الكشف.")
                    else:
                        st.info("حدد عمود الدائن/الإيداع أعلاه لعرض هذا التحليل.")

                    st.write("### 💸 أبرز المستفيدين (عمليات صادرة)")
                    if debit_col != '-- لا يوجد --':
                        withdrawals = work[work['_debit'].fillna(0) > 0]
                        if not withdrawals.empty:
                            summary2 = withdrawals.groupby('_party').agg(
                                عدد_العمليات=('_debit', 'count'),
                                إجمالي_المبلغ=('_debit', 'sum'),
                                طرق_الدفع=('_method', lambda s: ', '.join(sorted(set(s))))
                            ).sort_values('إجمالي_المبلغ', ascending=False).reset_index()
                            summary2.columns = ['الاسم / الجهة', 'عدد العمليات', 'إجمالي المبلغ', 'نوع العملية']
                            st.dataframe(summary2.head(15), use_container_width=True)
                        else:
                            st.info("لا توجد عمليات سحب/تحويل صادر في هذا الكشف.")
                    else:
                        st.info("حدد عمود المدين/السحب أعلاه لعرض هذا التحليل.")

                    st.write("### 🔝 أبرز العمليات الفردية (الأكبر مبلغًا)")
                    rows = []
                    for _, r in work.iterrows():
                        amt = r['_credit'] if (r['_credit'] not in (None,) and r['_credit'] and r['_credit'] > 0) else r['_debit']
                        direction = 'واردة (إيداع)' if (r['_credit'] and r['_credit'] > 0) else ('صادرة (سحب/تحويل)' if (r['_debit'] and r['_debit'] > 0) else None)
                        if amt is None or direction is None:
                            continue
                        rows.append({
                            'التاريخ': r[date_col] if date_col != '-- لا يوجد --' else '',
                            'الاسم / الجهة': r['_party'],
                            'المبلغ': amt,
                            'نوع الحركة': direction,
                            'طريقة العملية': r['_method'],
                        })
                    if rows:
                        top_tx = pd.DataFrame(rows).sort_values('المبلغ', ascending=False).head(15)
                        st.dataframe(top_tx, use_container_width=True)
                    else:
                        st.info("حدد أعمدة الدائن/المدين لعرض أبرز العمليات.")
                else:
                    st.info(
                        "لعرض تحليل (أبرز المودعين / المستفيدين / أكبر العمليات)، "
                        "اختر عمود 'تفاصيل العملية' من القائمة أعلاه، لأن التحليل يعتمد على "
                        "النص الوصفي لكل عملية لاستخراج اسم الطرف الآخر ونوع العملية."
                    )
