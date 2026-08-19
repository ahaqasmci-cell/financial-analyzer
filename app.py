import streamlit as st
import pandas as pd
import pdfplumber
import io
import re

st.set_page_config(page_title="المحلل المالي الذكي", layout="centered")

# ============================================================
# مكتبات اختيارية: تشكيل النص العربي + OCR للملفات الممسوحة ضوئيًا
# ============================================================
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    ARABIC_LIBS_AVAILABLE = True
except ImportError:
    ARABIC_LIBS_AVAILABLE = False

try:
    import pytesseract
    from pdf2image import convert_from_bytes
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


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


def extract_via_ocr(file_bytes, lang='ara+eng', col_gap_px=40):
    """
    آخر خطة: تحويل صفحات PDF لصور واستخراج النص عبر Tesseract OCR.
    يعتمد على إحداثيات كل كلمة (image_to_data) لتجميعها في أسطر ثم أعمدة،
    بدل الاعتماد على المسافات النصية التي غالبًا لا تكون دقيقة في مخرجات OCR.
    """
    from pytesseract import Output
    raw_rows = []
    debug_text_pages = []

    try:
        images = convert_from_bytes(file_bytes, dpi=300)
    except Exception as e:
        return raw_rows, [f"فشل تحويل PDF لصور: {e}"]

    for img in images:
        try:
            data = pytesseract.image_to_data(img, lang=lang, output_type=Output.DICT)
        except Exception as e:
            # قد تكون حزمة اللغة العربية غير مثبتة على السيرفر
            try:
                data = pytesseract.image_to_data(img, lang='eng', output_type=Output.DICT)
                debug_text_pages.append(f"تحذير: تعذر استخدام اللغة العربية ({e})، تم الرجوع للإنجليزية فقط.")
            except Exception as e2:
                debug_text_pages.append(f"فشل OCR كليًا على هذه الصفحة: {e2}")
                continue

        # نص الصفحة كاملاً لأغراض التشخيص فقط
        debug_text_pages.append(' '.join(w for w in data.get('text', []) if w.strip()))

        # تجميع الكلمات في أسطر بناءً على (block, paragraph, line)
        lines = {}
        for i, word in enumerate(data['text']):
            word = word.strip()
            if word == '':
                continue
            key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
            lines.setdefault(key, []).append({
                'text': word,
                'left': data['left'][i],
                'top': data['top'][i],
            })

        # ترتيب الأسطر من الأعلى للأسفل
        for key, words in sorted(lines.items(), key=lambda kv: min(w['top'] for w in kv[1])):
            words_sorted = sorted(words, key=lambda w: w['left'])
            columns = []
            current = [words_sorted[0]]
            for w in words_sorted[1:]:
                if w['left'] - current[-1]['left'] > col_gap_px:
                    columns.append(' '.join(x['text'] for x in current))
                    current = [w]
                else:
                    current.append(w)
            columns.append(' '.join(x['text'] for x in current))
            if len(columns) >= 3:
                raw_rows.append(columns)

    return raw_rows, debug_text_pages


# ============================================================
# استخراج اسم الطرف الآخر ونوع العملية من نص تفاصيل العملية
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
    for kw, label in METHOD_KEYWORDS:
        if kw in description or kw in description.lower():
            return label
    return 'أخرى'


def extract_party_name(description):
    if not isinstance(description, str) or description.strip() == '':
        return 'غير محدد'
    for pat in NAME_PATTERNS:
        m = re.search(pat, description)
        if m:
            name = re.sub(r'\s{2,}', ' ', m.group(1).strip())
            if len(name) >= 3:
                return name
    return description.strip()[:40]


def build_excel(df, general_stats, deposits_summary, beneficiaries_summary, top_tx):
    """يبني ملف إكسل بورقتين: البيانات الخام + التحليل المالي."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Bank_Report')

        sheet_name = 'التحليل_المالي'
        row = 0

        if general_stats:
            pd.DataFrame(general_stats, columns=['المؤشر', 'القيمة']).to_excel(
                writer, sheet_name=sheet_name, index=False, startrow=row
            )
            row += len(general_stats) + 3

        if deposits_summary is not None and not deposits_summary.empty:
            pd.DataFrame([['أبرز المودعين (عمليات واردة)']]).to_excel(
                writer, sheet_name=sheet_name, index=False, header=False, startrow=row
            )
            row += 2
            deposits_summary.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row)
            row += len(deposits_summary) + 3

        if beneficiaries_summary is not None and not beneficiaries_summary.empty:
            pd.DataFrame([['أبرز المستفيدين (عمليات صادرة)']]).to_excel(
                writer, sheet_name=sheet_name, index=False, header=False, startrow=row
            )
            row += 2
            beneficiaries_summary.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row)
            row += len(beneficiaries_summary) + 3

        if top_tx is not None and not top_tx.empty:
            pd.DataFrame([['أبرز العمليات الفردية']]).to_excel(
                writer, sheet_name=sheet_name, index=False, header=False, startrow=row
            )
            row += 2
            top_tx.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row)

        if row == 0:
            pd.DataFrame([['لم يتم تحديد أعمدة كافية لبناء التحليل المالي.']]).to_excel(
                writer, sheet_name=sheet_name, index=False, header=False
            )

    return output.getvalue()


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
    use_ocr = st.checkbox(
        "تفعيل OCR للملفات الممسوحة ضوئيًا (أبطأ، يُستخدم فقط عند فشل الطرق الأخرى)",
        value=True, disabled=not OCR_AVAILABLE,
        help="يحتاج تثبيت: pytesseract, pdf2image, وبرنامج tesseract + poppler على السيرفر" if not OCR_AVAILABLE else None
    )
    col_gap_px = st.slider(
        "المسافة بين الأعمدة عند OCR (بالبكسل) — زِد الرقم لو تجمّعت أعمدة معًا خطأ، قلّله لو تفرقت خطأ",
        min_value=15, max_value=100, value=40, step=5, disabled=not OCR_AVAILABLE
    )

uploaded_file = st.file_uploader("قم برفع كشف الحساب (PDF)", type=["pdf"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()

    with st.spinner("جاري تحليل الكشف..."):
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            raw_data = extract_via_tables(pdf)
            extraction_method = "جداول PDF (extract_tables)"
            if len(raw_data) < 2:
                raw_data = extract_via_text(pdf)
                extraction_method = "استخراج نصي احتياطي (extract_text)"

        ocr_debug_pages = []
        if len(raw_data) < 2 and use_ocr and OCR_AVAILABLE:
            with st.spinner("لم يتم إيجاد نص مباشر — جاري تشغيل OCR (قد يستغرق دقيقة)..."):
                raw_data, ocr_debug_pages = extract_via_ocr(file_bytes, col_gap_px=col_gap_px)
                extraction_method = "التعرف الضوئي على الحروف (OCR)"

        if len(raw_data) < 2:
            msg = "لم يتم العثور على بيانات منظمة في جدول داخل ملف PDF."
            if not OCR_AVAILABLE:
                msg += " الملف يبدو ممسوحًا ضوئيًا ويحتاج OCR — لكن مكتبات OCR غير مثبتة على هذا السيرفر (راجع ملاحظة packages.txt بالأسفل)."
            elif not use_ocr:
                msg += " فعّل خيار OCR من الإعدادات المتقدمة أعلاه."
            else:
                msg += " جُرّب OCR وقرأ نصًا، لكن تعذّر تقسيمه لأعمدة بالإعدادات الحالية — جرّب تغيير 'المسافة بين الأعمدة' من الإعدادات المتقدمة، أو راجع النص الخام أدناه."
            st.error(msg)
            if ocr_debug_pages:
                with st.expander("🔍 عرض النص الخام الذي استخرجه OCR (لأغراض التشخيص)"):
                    for i, txt in enumerate(ocr_debug_pages, 1):
                        st.text_area(f"صفحة {i}", txt, height=150)
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
            st.caption("راجع الأسماء المقترحة وعدّلها إذا لزم.")
            new_names = {}
            raw_cols = list(df.columns)
            for i in range(0, len(raw_cols), 2):
                cols_ui = st.columns(2)
                for j, orig in enumerate(raw_cols[i:i + 2]):
                    with cols_ui[j]:
                        suggested = suggest_header_name(orig)
                        new_names[orig] = st.text_input(f"العمود: `{orig}`", value=suggested, key=f"col_{i}_{j}")
            df = df.rename(columns=new_names)

            # ---------- تحديد الأعمدة (يُحسب مرة واحدة، يُستخدم في العرض والتصدير) ----------
            st.write("### تحديد الأعمدة")
            cols = list(df.columns)
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

            # ---------- حساب كل التحليلات مرة واحدة ----------
            general_stats = [('إجمالي عدد العمليات', len(df))]
            total_credit = total_debit = None
            if credit_col != '-- لا يوجد --':
                total_credit = df[credit_col].apply(clean_amount).sum()
                general_stats.append(('إجمالي الإيداعات', f"{total_credit:,.2f}"))
            if debit_col != '-- لا يوجد --':
                total_debit = df[debit_col].apply(clean_amount).sum()
                general_stats.append(('إجمالي السحوبات', f"{total_debit:,.2f}"))
            if total_credit is not None and total_debit is not None:
                general_stats.append(('صافي الحركة', f"{total_credit - total_debit:,.2f}"))

            deposits_summary = beneficiaries_summary = top_tx_df = None
            balances = None

            if balance_col != '-- لا يوجد --':
                balances = df[balance_col].apply(clean_amount).dropna()

            if detail_col != '-- لا يوجد --':
                work = df.copy()
                work['_credit'] = df[credit_col].apply(clean_amount) if credit_col != '-- لا يوجد --' else None
                work['_debit'] = df[debit_col].apply(clean_amount) if debit_col != '-- لا يوجد --' else None
                work['_method'] = work[detail_col].apply(classify_method)
                work['_party'] = work[detail_col].apply(extract_party_name)

                if credit_col != '-- لا يوجد --':
                    deposits = work[work['_credit'].fillna(0) > 0]
                    if not deposits.empty:
                        deposits_summary = deposits.groupby('_party').agg(
                            عدد_العمليات=('_credit', 'count'),
                            إجمالي_المبلغ=('_credit', 'sum'),
                            طرق_الدفع=('_method', lambda s: ', '.join(sorted(set(s))))
                        ).sort_values('إجمالي_المبلغ', ascending=False).reset_index()
                        deposits_summary.columns = ['الاسم / الجهة', 'عدد العمليات', 'إجمالي المبلغ', 'نوع العملية']

                if debit_col != '-- لا يوجد --':
                    withdrawals = work[work['_debit'].fillna(0) > 0]
                    if not withdrawals.empty:
                        beneficiaries_summary = withdrawals.groupby('_party').agg(
                            عدد_العمليات=('_debit', 'count'),
                            إجمالي_المبلغ=('_debit', 'sum'),
                            طرق_الدفع=('_method', lambda s: ', '.join(sorted(set(s))))
                        ).sort_values('إجمالي_المبلغ', ascending=False).reset_index()
                        beneficiaries_summary.columns = ['الاسم / الجهة', 'عدد العمليات', 'إجمالي المبلغ', 'نوع العملية']

                tx_rows = []
                for _, r in work.iterrows():
                    is_credit = r['_credit'] and r['_credit'] > 0
                    is_debit = r['_debit'] and r['_debit'] > 0
                    if not is_credit and not is_debit:
                        continue
                    tx_rows.append({
                        'التاريخ': r[date_col] if date_col != '-- لا يوجد --' else '',
                        'الاسم / الجهة': r['_party'],
                        'المبلغ': r['_credit'] if is_credit else r['_debit'],
                        'نوع الحركة': 'واردة (إيداع)' if is_credit else 'صادرة (سحب/تحويل)',
                        'طريقة العملية': r['_method'],
                    })
                if tx_rows:
                    top_tx_df = pd.DataFrame(tx_rows).sort_values('المبلغ', ascending=False).head(15).reset_index(drop=True)

            excel_bytes = build_excel(
                df, general_stats,
                deposits_summary.head(15) if deposits_summary is not None else None,
                beneficiaries_summary.head(15) if beneficiaries_summary is not None else None,
                top_tx_df
            )

            # ---------- العرض ----------
            tab1, tab2 = st.tabs(["📋 الكشف المفرغ", "📈 ملخص التحليل المالي"])

            with tab1:
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    "📥 تصدير إلى Excel (ورقتين: البيانات + التحليل المالي)",
                    data=excel_bytes, file_name="Bank_Analysis_Report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            with tab2:
                st.write("### إحصائيات عامة")
                metric_cols = st.columns(len(general_stats))
                for mc, (label, value) in zip(metric_cols, general_stats):
                    mc.metric(label, value)

                if balances is not None and not balances.empty:
                    st.write("### تطور الرصيد")
                    st.line_chart(balances.reset_index(drop=True))

                if detail_col != '-- لا يوجد --':
                    st.write("---")
                    st.write("### 🏦 أبرز المودعين (عمليات واردة)")
                    if deposits_summary is not None:
                        st.dataframe(deposits_summary.head(15), use_container_width=True)
                    else:
                        st.info("لا توجد عمليات إيداع، أو لم يُحدَّد عمود الدائن.")

                    st.write("### 💸 أبرز المستفيدين (عمليات صادرة)")
                    if beneficiaries_summary is not None:
                        st.dataframe(beneficiaries_summary.head(15), use_container_width=True)
                    else:
                        st.info("لا توجد عمليات سحب/تحويل صادر، أو لم يُحدَّد عمود المدين.")

                    st.write("### 🔝 أبرز العمليات الفردية (الأكبر مبلغًا)")
                    if top_tx_df is not None:
                        st.dataframe(top_tx_df, use_container_width=True)
                    else:
                        st.info("حدد أعمدة الدائن/المدين لعرض أبرز العمليات.")
                else:
                    st.info("اختر عمود 'تفاصيل العملية' أعلاه لعرض تحليل المودعين والمستفيدين وأكبر العمليات.")
