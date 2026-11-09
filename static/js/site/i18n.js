// English / Arabic strings for the guest-facing pages (website, sign-in, guest account).
const STRINGS = {
  en: {
    lang: 'العربية', rooms: 'Rooms', reviews: 'Reviews', account: 'My account', signin: 'Sign in', signout: 'Sign out', register: 'Create account',
    heroTitle: 'Book your stay', arrival: 'Arrival', departure: 'Departure', adults: 'Adults', children: 'Children', promo: 'Promo code', search: 'Check availability',
    nights: 'night(s)', from: 'from', perNight: '/ night', total: 'Total', avgRate: 'average per night', book: 'Book now', left: 'left', upTo: 'Up to', guests: 'guests',
    noRooms: 'No rooms are available for these dates. Please try other dates.', taxesNote: 'Prices exclude {sc}% service charge and {vat}% VAT.',
    inclTaxes: 'incl. service & VAT', confirmBooking: 'Confirm your booking', specialRequests: 'Special requests (optional)', confirm: 'Confirm booking',
    booked: 'Your booking is confirmed!', ourRooms: 'Our rooms', guestReviews: 'What our guests say', checkIn: 'Check-in from', checkOut: 'Check-out until',
    myBookings: 'My bookings', profile: 'Profile', privacy: 'Privacy & data', bookAnother: 'Book a stay', cancel: 'Cancel booking', details: 'Details',
    bill: 'Your bill', roomService: 'Room service', requests: 'Requests', review: 'Rate your stay', invoice: 'Invoice', status: 'Status', balance: 'Balance',
    paid: 'Paid', subtotal: 'Subtotal', service: 'Service charge', vat: 'VAT', order: 'Place order', send: 'Send', back: 'Back',
    email: 'E-mail', password: 'Password', firstName: 'First name', lastName: 'Last name', phone: 'Phone', nationality: 'Nationality', address: 'Address',
    save: 'Save', forgot: 'Forgot password?', resetTitle: 'Reset your password', sendLink: 'Send reset link', newPassword: 'New password',
    code: 'Authentication code', verify: 'Verify', acceptPrivacy: 'I have read and accept the privacy notice', marketing: 'Send me offers and news',
    haveAccount: 'Already have an account?', noAccount: 'New guest?', exportData: 'Download my data', deleteAccount: 'Delete my account',
    privacyText: 'Under Egypt’s Personal Data Protection Law (151/2020) you can download the personal data we hold about you or ask us to erase it. Tax invoices are kept anonymously as required by law.',
    roomNo: 'Room', noBookings: 'You have no bookings yet.', requestTypes: 'Request type', message: 'Message', stars: 'Rating', comment: 'Comment',
    thanksReview: 'Thank you for your review!', policy: 'Free cancellation until {d} day(s) before arrival.',
    verifyTitle: 'Confirm your e-mail address', verifyText: 'We sent a confirmation link to {email}. Open it to start using your account. The link works for 48 hours.',
    verifyResend: 'Send the link again', verifyDone: 'I have confirmed it', verifySent: 'A new link is on its way.',
    emailConfirmed: 'Your e-mail address is confirmed. Thank you!',
  },
  ar: {
    lang: 'English', rooms: 'الغرف', reviews: 'التقييمات', account: 'حسابي', signin: 'تسجيل الدخول', signout: 'تسجيل الخروج', register: 'إنشاء حساب',
    heroTitle: 'احجز إقامتك', arrival: 'الوصول', departure: 'المغادرة', adults: 'البالغون', children: 'الأطفال', promo: 'رمز الخصم', search: 'تحقق من التوفر',
    nights: 'ليلة', from: 'من', perNight: '/ الليلة', total: 'الإجمالي', avgRate: 'متوسط سعر الليلة', book: 'احجز الآن', left: 'متبقية', upTo: 'حتى', guests: 'ضيوف',
    noRooms: 'لا توجد غرف متاحة في هذه التواريخ. يرجى تجربة تواريخ أخرى.', taxesNote: 'الأسعار لا تشمل {sc}٪ خدمة و{vat}٪ ضريبة القيمة المضافة.',
    inclTaxes: 'شامل الخدمة والضريبة', confirmBooking: 'تأكيد الحجز', specialRequests: 'طلبات خاصة (اختياري)', confirm: 'تأكيد الحجز',
    booked: 'تم تأكيد حجزك!', ourRooms: 'غرفنا', guestReviews: 'آراء ضيوفنا', checkIn: 'تسجيل الوصول من', checkOut: 'تسجيل المغادرة حتى',
    myBookings: 'حجوزاتي', profile: 'الملف الشخصي', privacy: 'الخصوصية والبيانات', bookAnother: 'احجز إقامة', cancel: 'إلغاء الحجز', details: 'التفاصيل',
    bill: 'فاتورتك', roomService: 'خدمة الغرف', requests: 'الطلبات', review: 'قيّم إقامتك', invoice: 'الفاتورة', status: 'الحالة', balance: 'الرصيد',
    paid: 'المدفوع', subtotal: 'المجموع الفرعي', service: 'رسوم الخدمة', vat: 'ضريبة القيمة المضافة', order: 'اطلب الآن', send: 'إرسال', back: 'رجوع',
    email: 'البريد الإلكتروني', password: 'كلمة المرور', firstName: 'الاسم الأول', lastName: 'اسم العائلة', phone: 'الهاتف', nationality: 'الجنسية', address: 'العنوان',
    save: 'حفظ', forgot: 'نسيت كلمة المرور؟', resetTitle: 'إعادة تعيين كلمة المرور', sendLink: 'إرسال رابط إعادة التعيين', newPassword: 'كلمة المرور الجديدة',
    code: 'رمز التحقق', verify: 'تحقق', acceptPrivacy: 'قرأت إشعار الخصوصية وأوافق عليه', marketing: 'أرسلوا لي العروض والأخبار',
    haveAccount: 'لديك حساب بالفعل؟', noAccount: 'ضيف جديد؟', exportData: 'تنزيل بياناتي', deleteAccount: 'حذف حسابي',
    privacyText: 'وفقًا لقانون حماية البيانات الشخصية المصري رقم 151 لسنة 2020 يمكنك تنزيل بياناتك الشخصية أو طلب حذفها. تُحفظ الفواتير الضريبية دون بيانات شخصية كما يقتضي القانون.',
    roomNo: 'الغرفة', noBookings: 'لا توجد حجوزات بعد.', requestTypes: 'نوع الطلب', message: 'الرسالة', stars: 'التقييم', comment: 'تعليق',
    thanksReview: 'شكرًا لتقييمك!', policy: 'إلغاء مجاني حتى {d} يوم قبل الوصول.',
    verifyTitle: 'أكّد بريدك الإلكتروني', verifyText: 'أرسلنا رابط تأكيد إلى {email}. افتحه لتبدأ استخدام حسابك. الرابط صالح لمدة 48 ساعة.',
    verifyResend: 'أرسل الرابط مرة أخرى', verifyDone: 'لقد أكّدت بريدي', verifySent: 'رابط جديد في الطريق إليك.',
    emailConfirmed: 'تم تأكيد بريدك الإلكتروني. شكرًا لك!',
  },
};

let lang = 'en';
try { lang = localStorage.getItem('lang') === 'ar' ? 'ar' : 'en'; } catch (e) { /* storage unavailable */ }

export const getLang = () => lang;
export function t(key, vars = {}) {
  let s = (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key;
  Object.entries(vars).forEach(([k, v]) => { s = s.replace(`{${k}}`, v); });
  return s;
}
export function applyDirection() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
}
export function toggleLang() {
  lang = lang === 'ar' ? 'en' : 'ar';
  try { localStorage.setItem('lang', lang); } catch (e) { /* ignore */ }
  location.reload();
}
applyDirection();
