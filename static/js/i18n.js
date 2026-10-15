/* ExpoPulse Arabic / English interface switch.
 *
 * Presentation only: the server keeps rendering English, and this script
 * translates what is on screen when Arabic is selected. Nothing that is sent
 * to Django (form values, filters, URLs) is changed, so the backend, the
 * tests and the detectors are unaffected.
 *
 * - The choice is remembered per browser (localStorage "expopulse-lang").
 * - Arabic switches the page to right-to-left (<html lang="ar" dir="rtl">).
 * - Text that the dashboard adds later (live polling) is translated as it
 *   appears, through a MutationObserver.
 * - Incident descriptions written by people or detectors are left as they
 *   are; fixed interface text, labels and known demo names are translated.
 *
 * To add a translation: add the exact English text to TEXT below.
 */
(function () {
    "use strict";

    const KEY = "expopulse-lang";
    const root = document.documentElement;

    // ------------------------------------------------------------ exact text
    const TEXT = {
        // Navigation and shell
        "Dashboard": "لوحة التحكم",
        "Incidents": "البلاغات",
        "Manual report": "بلاغ يدوي",
        "Teams": "الفرق",
        "Theme": "المظهر",
        "System": "حسب النظام",
        "Light": "فاتح",
        "Dark": "داكن",
        "Skip to main content": "تخطَّ إلى المحتوى الرئيسي",
        "Main navigation": "التنقل الرئيسي",
        "Change color theme": "تغيير المظهر",
        "Color theme": "المظهر",
        "Local time": "الوقت المحلي",
        "ExpoPulse, go to dashboard": "نبض إكسبو، الانتقال إلى لوحة التحكم",

        // Dashboard
        "Operations dashboard": "لوحة العمليات",
        "Live incident picture · prioritized by severity and impact. Select a priority or status to focus the queue.":
            "صورة حيّة للبلاغات مرتّبة حسب الخطورة والأثر. اختر أولوية أو حالة لتصفية القائمة.",
        "Connecting live updates…": "جارٍ الاتصال بالتحديثات المباشرة…",
        "Live update unavailable · retrying…": "التحديث المباشر غير متاح · جارٍ إعادة المحاولة…",
        "Manual incident report": "تسجيل بلاغ يدوي",
        "High priority": "أولوية عالية",
        "Active now": "النشطة الآن",
        "Resolved today": "المحلولة اليوم",
        "Teams free": "الفرق المتاحة",
        "Show all incidents": "عرض كل البلاغات",
        "Open incidents by priority": "البلاغات المفتوحة حسب الأولوية",
        "Where incidents stand": "حالة البلاغات",
        "total": "الإجمالي",
        "Most urgent first": "الأكثر إلحاحاً أولاً",
        "Show everything": "عرض الكل",
        "No incidents match this selection.": "لا توجد بلاغات تطابق هذا الاختيار.",

        // Table headings and shared labels
        "ID": "الرقم",
        "Incident": "البلاغ",
        "Type": "النوع",
        "Location": "الموقع",
        "Priority": "الأولوية",
        "Status": "الحالة",
        "Team": "الفريق",
        "Time": "الوقت",
        "Title": "العنوان",
        "Source": "المصدر",
        "Created": "وقت الإنشاء",
        "Updated": "آخر تحديث",
        "No team yet": "لم يُسنَد فريق بعد",
        "Not yet": "ليس بعد",
        "Unknown": "غير معروف",

        // Priority / severity
        "Critical": "حرج",
        "High": "عالٍ",
        "Medium": "متوسط",
        "Low": "منخفض",

        // Incident status
        "New": "جديد",
        "Assigned": "مُسنَد",
        "In progress": "قيد التنفيذ",
        "In Progress": "قيد التنفيذ",
        "Resolved": "محلول",

        // Incident types
        "Crowding": "ازدحام",
        "Medical": "طبي",
        "Security": "أمني",
        "Maintenance": "صيانة",
        "IT": "تقنية المعلومات",
        "Cleaning": "نظافة",
        "Accessibility": "إمكانية الوصول",
        "Other": "أخرى",

        // Team types and status
        "Visitor Services": "خدمات الزوار",
        "Available": "متاح",
        "Busy": "مشغول",
        "Offline": "غير متصل",

        // Monitoring channels
        "Elevator & Escalator Fault Monitoring": "مراقبة أعطال المصاعد والسلالم الكهربائية",
        "CCTV Restricted-Area Detection": "رصد دخول المناطق المحظورة بالكاميرات",
        "CCTV Fall Detection": "رصد السقوط بالكاميرات",
        "CCTV Crowd Detection": "رصد الازدحام بالكاميرات",
        "CCTV Monitoring": "المراقبة بالكاميرات",
        "Operator report": "بلاغ من المشغّل",
        "Other source": "مصدر آخر",

        // Incident sources (demo data)
        "Security Staff": "موظفو الأمن",
        "Maintenance System": "نظام الصيانة",
        "IT Monitoring": "مراقبة تقنية المعلومات",
        "Cleaning Team": "فريق النظافة",
        "Access Control System": "نظام التحكم بالدخول",
        "Sensor Network": "شبكة الحساسات",
        "Equipment Monitoring": "مراقبة المعدات",
        "Manual Report": "بلاغ يدوي",

        // Locations (demo data)
        "Main Entrance": "المدخل الرئيسي",
        "Food Court": "ساحة المطاعم",
        "Transport Hub": "مركز النقل",
        "Visitor Services Center": "مركز خدمات الزوار",
        "North Gate": "البوابة الشمالية",
        "East Gate": "البوابة الشرقية",
        "Central Food Court": "ساحة المطاعم المركزية",

        // Demo incidents (seed_data)
        "Medical Emergency": "حالة طبية طارئة",
        "Heavy Crowd at Gate 4": "ازدحام شديد عند البوابة 4",
        "Visitor Congestion at Gate 4": "تكدّس الزوار عند البوابة 4",
        "Elevator Failure": "تعطّل المصعد",
        "Access Scanner Offline": "جهاز مسح الدخول متوقف",
        "Spill in Food Court": "انسكاب في ساحة المطاعم",
        "A visitor requires immediate medical assistance.": "زائر يحتاج إلى مساعدة طبية فورية.",
        "A large crowd is forming at the east gate.": "يتشكّل ازدحام كبير عند البوابة الشرقية.",
        "Security staff report continued congestion at the east gate.": "يُبلغ موظفو الأمن عن استمرار التكدّس عند البوابة الشرقية.",
        "The main elevator in Pavilion 12 is not operating.": "المصعد الرئيسي في الجناح 12 لا يعمل.",
        "The access scanner at the main entrance is offline.": "جهاز مسح الدخول عند المدخل الرئيسي متوقف.",
        "A spill has been reported near the central seating area.": "تم الإبلاغ عن انسكاب قرب منطقة الجلوس المركزية.",

        // Incident list
        "All incidents": "كل البلاغات",
        "Archived incidents": "البلاغات المؤرشفة",
        "Active incidents": "البلاغات النشطة",
        "View archive": "عرض الأرشيف",
        "Any priority": "كل الأولويات",
        "Any status": "كل الحالات",
        "Any type": "كل الأنواع",
        "Any location": "كل المواقع",
        "Search title or ID": "ابحث بالعنوان أو الرقم",
        "Apply": "تطبيق",
        "Clear": "مسح",
        "Restore selected": "استعادة المحدد",
        "Archive selected": "أرشفة المحدد",
        "Prepare demo": "تجهيز العرض التجريبي",
        "Restore selected archived incidents?": "استعادة البلاغات المؤرشفة المحددة؟",
        "Archive the selected resolved incidents?": "أرشفة البلاغات المحلولة المحددة؟",
        "Archive all resolved incidents?": "أرشفة كل البلاغات المحلولة؟",
        "Prepare demo? This will resolve and archive all current incidents and release their busy teams. History remains available. Ensure simulations are stopped first.":
            "تجهيز العرض التجريبي؟ سيتم حل كل البلاغات الحالية وأرشفتها وتحرير الفرق المشغولة. يبقى السجل متاحاً. تأكد من إيقاف المحاكاة أولاً.",
        "Select all displayed incidents": "تحديد كل البلاغات المعروضة",
        "Select at least one incident.": "حدّد بلاغاً واحداً على الأقل.",
        "No incidents match these filters.": "لا توجد بلاغات تطابق هذه الفلاتر.",
        "Clear the filters": "امسح الفلاتر",
        "to see everything.": "لعرض كل البلاغات.",

        // Incident detail
        "Back to all incidents": "العودة إلى كل البلاغات",
        "Progress": "مراحل البلاغ",
        "Possible duplicate of": "يُحتمل أنه مكرر لـ",
        ". Check before sending a second team.": ". تحقّق قبل إرسال فريق ثانٍ.",
        "Detected issue": "المشكلة المرصودة",
        "No description was given.": "لم يُكتب وصف.",
        "Operator response guidance": "إرشادات الاستجابة للمشغّل",
        "Severity": "الخطورة",
        "Equipment ID": "رقم المعدة",
        "Equipment type": "نوع المعدة",
        "Fault detected": "العطل المرصود",
        "Passenger impact": "الأثر على الركاب",
        "Not reported": "غير مُبلَّغ عنه",
        "Requires operator verification": "يتطلب تحقق المشغّل",
        "People affected (reported)": "عدد المتأثرين (حسب البلاغ)",
        "Incident category": "فئة البلاغ",
        "Monitoring channel": "قناة المراقبة",
        "Incident workflow": "سير معالجة البلاغ",
        "Response actions": "إجراءات الاستجابة",
        "Suggested team:": "الفريق المقترح:",
        "Confirm team assignment": "تأكيد إسناد الفريق",
        "No suitable team is currently available.": "لا يوجد فريق مناسب متاح حالياً.",
        "Start incident response": "بدء الاستجابة للبلاغ",
        "Mark as resolved": "تحديد كمحلول",
        "Resolve this incident and release its team?": "حل هذا البلاغ وتحرير فريقه؟",
        "Incident resolved.": "تم حل البلاغ.",
        "Elevator": "مصعد",
        "Escalator": "سلم كهربائي",
        "Equipment": "معدات",
        "Door Stuck": "باب عالق",
        "Emergency Stop": "توقف طارئ",
        "Motor Fault": "عطل في المحرك",
        "Out of Service": "خارج الخدمة",
        "Fault Detected": "تم رصد عطل",
        "Have maintenance verify the reported fault, check whether anyone needs assistance, and assess safe operation. Escalate immediately if people are trapped or injured. The simulated telemetry has not confirmed passenger impact.":
            "اطلب من فريق الصيانة التحقق من العطل المُبلَّغ عنه، والتأكد إن كان أحد يحتاج مساعدة، وتقييم سلامة التشغيل. صعّد فوراً إذا كان هناك أشخاص محتجزون أو مصابون. بيانات المحاكاة لم تؤكد وجود أثر على الركاب.",
        "Have maintenance verify the reported fault, check whether anyone needs assistance, and assess safe operation. Escalate immediately if people are trapped or injured. The external status feed reports availability only; it does not confirm the cause or any passenger impact.":
            "اطلب من فريق الصيانة التحقق من العطل المُبلَّغ عنه، والتأكد إن كان أحد يحتاج مساعدة، وتقييم سلامة التشغيل. صعّد فوراً إذا كان هناك أشخاص محتجزون أو مصابون. مصدر البيانات الخارجي يوضح حالة التشغيل فقط، ولا يؤكد سبب العطل أو وجود أثر على الركاب.",
        "Ask security to verify the footage and check the restricted zone before taking action.":
            "اطلب من فريق الأمن مراجعة التسجيل وتفقّد المنطقة المحظورة قبل اتخاذ أي إجراء.",
        "Ask security to verify crowding and assess safe movement through the affected area.":
            "اطلب من فريق الأمن التحقق من الازدحام وتقييم سلامة الحركة في المنطقة المتأثرة.",
        "Request immediate operator verification and medical assessment where necessary.":
            "اطلب تحققاً فورياً من المشغّل وتقييماً طبياً عند الحاجة.",

        // Manual report form
        "Report incident manually": "تسجيل بلاغ يدوي",
        "Use this form for staff or operator reports. CCTV and equipment alerts are generated automatically. Priority and possible duplicates are calculated when you submit.":
            "استخدم هذا النموذج لبلاغات الموظفين أو المشغّلين. تنبيهات الكاميرات والمعدات تُنشأ تلقائياً. تُحسب الأولوية والبلاغات المكررة المحتملة عند الإرسال.",
        "Reporting channel:": "قناة البلاغ:",
        ". Automated monitoring sources cannot be selected here.": ". لا يمكن اختيار مصادر المراقبة الآلية من هنا.",
        "Description": "الوصف",
        "Incident type": "نوع البلاغ",
        "People affected": "عدد المتأثرين",
        "Estimated number; use 0 if unknown.": "عدد تقديري؛ اكتب 0 إذا كان غير معروف.",
        "A rough number is fine.": "يكفي رقم تقريبي.",
        "- Select an option -": "- اختر -",
        "---------": "- اختر -",
        "Choose a type": "اختر النوع",
        "Choose a source": "اختر المصدر",
        "Choose a location": "اختر الموقع",
        "Choose severity": "اختر الخطورة",
        "Send incident": "إرسال البلاغ",
        "Cancel": "إلغاء",
        "This field is required.": "هذا الحقل مطلوب.",
        "Enter zero or more.": "أدخل صفراً أو أكثر.",
        "Fill this in before sending.": "عبّئ هذا الحقل قبل الإرسال.",

        // Teams
        "Response teams": "فرق الاستجابة",
        "Response resources and current assignments. Base locations are not live GPS positions.":
            "موارد الاستجابة ومهامها الحالية. المواقع الأساسية ليست مواقع GPS مباشرة.",
        "Base location": "الموقع الأساسي",
        "Working on": "المهمة الحالية",
        "No active assignment": "لا توجد مهمة نشطة",
        "Team offline": "الفريق غير متصل",
        "No response teams have been added yet.": "لم تتم إضافة فرق استجابة بعد.",

        // Server messages
        "No suitable team is available.": "لا يوجد فريق مناسب متاح.",
        "Only new incidents can receive an initial assignment.": "يمكن إسناد فريق للبلاغات الجديدة فقط.",
        "Assign a team first.": "أسنِد فريقاً أولاً.",
        "Incident is now in progress.": "البلاغ الآن قيد التنفيذ.",
        "Incident resolved and team released.": "تم حل البلاغ وتحرير الفريق.",
        "No valid next status transition.": "لا توجد مرحلة تالية صالحة.",
        "Invalid incident-management action.": "إجراء غير صالح.",
        "Confirm the action before continuing.": "أكّد الإجراء قبل المتابعة.",
        "Select valid incidents (maximum 500).": "حدّد بلاغات صالحة (500 كحد أقصى).",
        "Only resolved incidents can be archived individually. Use Prepare Demo to close an active queue.":
            "يمكن أرشفة البلاغات المحلولة فقط بشكل فردي. استخدم «تجهيز العرض التجريبي» لإغلاق القائمة النشطة.",

        // Live cameras page
        "Live cameras": "الكاميرات المباشرة",
        "All simulated CCTV streams on one screen, with the latest alert from each camera.":
            "كل بثوث الكاميرات في شاشة واحدة، مع آخر تنبيه من كل كاميرا.",
        "Crowd camera": "كاميرا الازدحام",
        "Restricted-area camera": "كاميرا المنطقة المحظورة",
        "Fall-detection camera": "كاميرا رصد السقوط",
        "LIVE": "مباشر",
        "Camera offline": "الكاميرا غير متصلة",
        "Start the simulation to see this camera.": "شغّل المحاكاة لعرض هذه الكاميرا.",
        "Full screen": "ملء الشاشة",
        "Last alert": "آخر تنبيه",
        "No alerts from this camera yet.": "لا توجد تنبيهات من هذه الكاميرا بعد.",
        "Run": "شغّل",
        "to start all cameras. The streams are recorded footage replayed as live video, not physical CCTV cameras.":
            "لتشغيل كل الكاميرات. البث عبارة عن مقاطع مسجّلة تُعرض كبث مباشر، وليست كاميرات مراقبة فعلية.",

        // Footer
        "Smart Operations Center": "مركز العمليات الذكي",
        "Unified incident monitoring, intelligent prioritization, and coordinated response for Expo 2030.": "مراقبة موحّدة للحوادث وتحديد ذكي للأولويات وتنسيق الاستجابة لإكسبو 2030.",
        "Quick Links": "روابط سريعة",
        "Operations Dashboard": "لوحة مركز العمليات",
        "Response Teams": "فرق الاستجابة",
        "Footer quick links": "روابط التذييل السريعة",
        "Project": "المشروع",
        "GitHub Repository": "مستودع GitHub",
        "Developed by Team Next Wave": "من تطوير فريق نكست ويف",
        "Expo 2030 Operations Center Prototype": "نموذج أولي لمركز عمليات إكسبو 2030",
        "About ExpoPulse": "عن نبض إكسبو",
        "ExpoPulse is a smart operations center for Expo 2030. It brings incidents from CCTV detection, equipment monitoring and staff reports into one queue, ranks them by priority and dispatches the right response team.":
            "نبض إكسبو (ExpoPulse) مركز عمليات ذكي لمعرض إكسبو 2030. يجمع البلاغات من كاميرات المراقبة ومراقبة المعدات وبلاغات الموظفين في قائمة واحدة، ويرتّبها حسب الأولوية، ويوجّه فريق الاستجابة المناسب.",
        "Expo 2030 Challenge 3.6": "تحدي إكسبو 2030 رقم 3.6",
        "Team members": "أعضاء الفريق",
        "Abdullah Saeed Albassami": "عبدالله سعيد البسامي",
        "Ammar Mohammed Abdulkarim": "عمار محمد عبدالكريم",
        "Nasser Yaseen Abdu Qasem": "ناصر ياسين عبده قاسم",
        "Mohammed Yousef Alfulaij": "محمد يوسف الفليج",
        "Team Leader · Backend": "قائد الفريق · الواجهة الخلفية",
        "Backend": "الواجهة الخلفية",
        "Frontend": "الواجهة الأمامية",
        "Testing": "الاختبار",
        "Built by the ExpoPulse team.": "من تطوير فريق نبض إكسبو.",
        "© 2026 ExpoPulse": "© 2026 نبض إكسبو"
    };

    // Words used inside composed sentences.
    const TEAM_KIND = {
        "Security": "الأمن", "Medical": "الإسعاف", "Maintenance": "الصيانة", "IT": "تقنية المعلومات",
        "Cleaning": "النظافة", "Visitor Services": "خدمات الزوار"
    };
    const RESPONSIBILITY = {
        "Crowd management and restricted-area response": "إدارة الحشود والاستجابة لدخول المناطق المحظورة",
        "Falls, injury and medical assistance": "حالات السقوط والإصابات والمساعدة الطبية",
        "Elevator, escalator and facility faults": "أعطال المصاعد والسلالم الكهربائية والمرافق",
        "Networks, access systems and IT faults": "الشبكات وأنظمة الدخول وأعطال تقنية المعلومات",
        "Spills, sanitation and cleaning requests": "الانسكابات والتعقيم وطلبات النظافة",
        "Visitor assistance and accessibility": "مساعدة الزوار وإمكانية الوصول"
    };
    // Arabic counting forms: [one, two, 3-10, 11+]
    const UNITS = {
        minute: ["دقيقة", "دقيقتان", "دقائق", "دقيقة"],
        hour: ["ساعة", "ساعتان", "ساعات", "ساعة"],
        day: ["يوم", "يومان", "أيام", "يومًا"],
        week: ["أسبوع", "أسبوعان", "أسابيع", "أسبوعًا"],
        month: ["شهر", "شهران", "أشهر", "شهرًا"],
        year: ["سنة", "سنتان", "سنوات", "سنة"],
        incident: ["بلاغ واحد", "بلاغان", "بلاغات", "بلاغًا"],
        team: ["فريق واحد", "فريقان", "فرق", "فريقًا"],
        newIncident: ["بلاغ جديد", "بلاغان جديدان", "بلاغات جديدة", "بلاغًا جديدًا"]
    };

    function count(n, unit) {
        const forms = UNITS[unit];
        n = Number(n);
        if (n === 1) return forms[0];
        if (n === 2) return forms[1];
        if (n >= 3 && n <= 10) return n + " " + forms[2];
        return n + " " + forms[3];
    }

    function sub(text) {
        const out = translate(text);
        return out === undefined ? text : out;
    }

    // Django's timesince: "3 minutes", "1 day, 2 hours" (with no-break spaces).
    function since(text) {
        const parts = text.split(/,\s*/).map(part => {
            const m = part.match(/^(\d+)\s+(minute|hour|day|week|month|year)s?$/);
            return m ? (m[1] === "0" ? null : count(m[1], m[2])) : undefined;
        });
        if (parts.some(p => p === undefined)) return undefined;
        const real = parts.filter(Boolean);
        return real.length ? "منذ " + real.join(" و") : "منذ أقل من دقيقة";
    }

    // ---------------------------------------------------- composed sentences
    const PATTERNS = [
        [/^(.+) \| ExpoPulse$/, m => sub(m[1]) + " | نبض إكسبو"],
        [/^Gate (\d+)$/, m => "البوابة " + m[1]],
        [/^Zone ([A-Z0-9]+)$/, m => "المنطقة " + m[1]],
        [/^Exhibition Hall ([A-Z0-9]+)$/, m => "قاعة المعارض " + m[1]],
        [/^Pavilion (\d+)$/, m => "الجناح " + m[1]],
        [/^(Security|Medical|Maintenance|IT|Cleaning|Visitor Services) Team (\d+)$/, m => "فريق " + TEAM_KIND[m[1]] + " " + m[2]],
        [/^Equipment Fault \[(.+)\]$/, m => "عطل معدات [" + m[1] + "]"],
        [/^CCTV Crowding Alert - (.+)$/, m => "تنبيه ازدحام من الكاميرات - " + sub(m[1])],
        [/^CCTV Restricted Zone \[(.+)\] - (.+)$/, m => "دخول منطقة محظورة [" + m[1] + "] - " + sub(m[2])],
        [/^CCTV Possible Fall - (.+)$/, m => "اشتباه سقوط من الكاميرات - " + sub(m[1])],
        [/^Possible Restricted-Area Entry — (.+)$/, m => "اشتباه دخول منطقة محظورة — " + sub(m[1])],
        [/^Possible Crowd Congestion — (.+)$/, m => "اشتباه ازدحام — " + sub(m[1])],
        [/^Possible Person Fall — (.+)$/, m => "اشتباه سقوط شخص — " + sub(m[1])],
        [/^(Elevator|Escalator|Equipment) (.+) — (.+)$/, m => sub(m[1]) + ": " + sub(m[2]) + " — " + sub(m[3])],
        [/^Fault: (.+)$/, m => "العطل: " + sub(m[1])],
        [/^Incident #(\d+)$/, m => "بلاغ #" + m[1]],
        [/^incident #(\d+)(?:, (.+))?$/, m => "البلاغ #" + m[1] + (m[2] ? "، " + sub(m[2]) : "")],
        [/^⚠ Possible duplicate of #(\d+)$/, m => "⚠ يُحتمل أنه مكرر للبلاغ #" + m[1]],
        [/^Score (\d+)$/, m => "الدرجة " + m[1]],
        [/^(.+) ago$/, m => since(m[1])],
        [/^Live updates active · last checked (.+)$/, m => "التحديث المباشر يعمل · آخر فحص " + m[1]],
        [/^(\d+) new incidents? since opening this dashboard\. Latest:$/, m => count(m[1], "newIncident") + " منذ فتح لوحة التحكم. الأحدث:"],
        [/^#(\d+) — (.+)$/, m => "#" + m[1] + " — " + sub(m[2])],
        [/^#(\d+) (.+)$/, m => "#" + m[1] + " " + sub(m[2])],
        [/^(.+): (\d+) incidents?$/, m => sub(m[1]) + ": " + count(m[2], "incident")],
        [/^(.+): (\d+) open incidents$/, m => sub(m[1]) + ": " + count(m[2], "incident") + " مفتوحة"],
        [/^(\d+) incidents? shown\.$/, m => "عدد البلاغات المعروضة: " + m[1]],
        [/^(\d+) teams?, (\d+) available\.$/, m => count(m[1], "team") + "، المتاح منها " + m[2] + "."],
        [/^Responsibilities: (.+)$/, m => RESPONSIBILITY[m[1]] ? "المسؤوليات: " + RESPONSIBILITY[m[1]] : undefined],
        [/^Responding to: (.+)$/, m => "يستجيب في: " + sub(m[1])],
        [/^Archive all resolved \((\d+)\)$/, m => "أرشفة كل المحلولة (" + m[1] + ")"],
        [/^Select incident (\d+)$/, m => "تحديد البلاغ " + m[1]],
        [/^Incident #(\d+) created successfully\.$/, m => "تم إنشاء البلاغ #" + m[1] + " بنجاح."],
        [/^(.+) assigned successfully\.$/, m => "تم إسناد " + sub(m[1]) + " بنجاح."],
        [/^Restored (\d+) archived incident\(s\)\.$/, m => "تمت استعادة " + count(m[1], "incident") + " من الأرشيف."],
        [/^(Demo queue prepared|Incidents archived): (\d+) incident\(s\)\. History preserved\.$/,
            m => (m[1] === "Incidents archived" ? "تمت الأرشفة" : "تم تجهيز العرض التجريبي") + ": " + count(m[2], "incident") + ". السجل محفوظ."],
        [/^(Crowd camera|Restricted-area camera|Fall-detection camera) live stream$/, m => "بث مباشر: " + sub(m[1])],
        [/^Live cameras \| ExpoPulse$/, () => "الكاميرات المباشرة | نبض إكسبو"],
        [/^Color theme: (system|light|dark)\. Change color theme$/,
            m => "المظهر: " + { system: "حسب النظام", light: "فاتح", dark: "داكن" }[m[1]] + ". تغيير المظهر"]
    ];

    function translate(text) {
        if (Object.prototype.hasOwnProperty.call(TEXT, text)) return TEXT[text];
        for (const [regex, build] of PATTERNS) {
            const m = text.match(regex);
            if (m) {
                const out = build(m);
                if (out !== undefined) return out;
            }
        }
        return undefined;
    }

    // Public helper for alert()/confirm() text built in JavaScript.
    function t(text) {
        return root.lang === "ar" ? sub(text) : text;
    }

    // ------------------------------------------------------------ DOM work
    const ATTRS = ["placeholder", "title", "aria-label", "data-confirm", "data-manage-confirm"];
    const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "NOSCRIPT"]);
    const textMemory = new WeakMap();   // text node -> {en, ar}
    const attrMemory = new WeakMap();   // element -> {attr: {en, ar}}
    let titleMemory = null;

    function skipped(node) {
        const parent = node.nodeType === 3 ? node.parentElement : node;
        return !parent || SKIP.has(parent.tagName) || !!parent.closest("[data-no-i18n]");
    }

    function translateText(node) {
        if (skipped(node)) return;
        const raw = node.data;
        const key = raw.replace(/\s+/g, " ").trim();
        if (!key) return;
        const out = translate(key);
        if (out === undefined || out === key) return;
        const lead = raw.match(/^\s*/)[0];
        const trail = raw.match(/\s*$/)[0];
        const ar = lead + out + trail;
        textMemory.set(node, { en: raw, ar });
        node.data = ar;
    }

    function translateAttr(el, name) {
        if (skipped(el)) return;
        const raw = el.getAttribute(name);
        if (!raw) return;
        const out = translate(raw.replace(/\s+/g, " ").trim());
        if (out === undefined || out === raw) return;
        const saved = attrMemory.get(el) || {};
        saved[name] = { en: raw, ar: out };
        attrMemory.set(el, saved);
        el.setAttribute(name, out);
    }

    function translateTree(start) {
        if (start.nodeType === 3) { translateText(start); return; }
        if (start.nodeType !== 1 || skipped(start)) return;
        const walker = document.createTreeWalker(start, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(translateText);
        const selector = ATTRS.map(a => "[" + a + "]").join(",");
        const elements = [start, ...start.querySelectorAll(selector)];
        elements.forEach(el => ATTRS.forEach(a => { if (el.hasAttribute && el.hasAttribute(a)) translateAttr(el, a); }));
    }

    function restoreTree() {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
            const node = walker.currentNode;
            const saved = textMemory.get(node);
            if (saved && node.data === saved.ar) node.data = saved.en;
            textMemory.delete(node);
        }
        document.body.querySelectorAll(ATTRS.map(a => "[" + a + "]").join(",")).forEach(el => {
            const saved = attrMemory.get(el);
            if (!saved) return;
            Object.keys(saved).forEach(a => {
                if (el.getAttribute(a) === saved[a].ar) el.setAttribute(a, saved[a].en);
            });
            attrMemory.delete(el);
        });
        if (titleMemory && document.title === titleMemory.ar) document.title = titleMemory.en;
        titleMemory = null;
    }

    function translateTitle() {
        const out = translate(document.title);
        if (out !== undefined && out !== document.title) {
            titleMemory = { en: document.title, ar: out };
            document.title = out;
        }
    }

    const observer = new MutationObserver(records => {
        if (root.lang !== "ar") return;
        records.forEach(record => {
            if (record.type === "characterData") translateText(record.target);
            else if (record.type === "attributes") translateAttr(record.target, record.attributeName);
            else record.addedNodes.forEach(translateTree);
        });
    });

    // --------------------------------------------------------- the switch
    const button = document.getElementById("lang-toggle");

    function updateButton(lang) {
        if (!button) return;
        const toArabic = lang !== "ar";
        button.querySelector(".lang-label").textContent = toArabic ? "العربية" : "English";
        button.setAttribute("lang", toArabic ? "ar" : "en");
        button.setAttribute("aria-label", toArabic ? "التبديل إلى العربية" : "Switch to English");
        button.title = toArabic ? "التبديل إلى العربية" : "Switch to English";
    }

    function apply(lang) {
        const arabic = lang === "ar";
        root.lang = arabic ? "ar" : "en";
        root.dir = arabic ? "rtl" : "ltr";
        if (arabic) { translateTree(document.body); translateTitle(); }
        else restoreTree();
        updateButton(lang);
        // Keep the observer's own changes out of its queue.
        observer.takeRecords();
    }

    let lang = "en";
    try { if (localStorage.getItem(KEY) === "ar") lang = "ar"; } catch (_) { /* storage unavailable */ }

    if (button) {
        button.addEventListener("click", () => {
            lang = root.lang === "ar" ? "en" : "ar";
            try { localStorage.setItem(KEY, lang); } catch (_) { /* choice lasts for this page only */ }
            apply(lang);
        });
    }

    observer.observe(document.body, {
        subtree: true, childList: true, characterData: true,
        attributes: true, attributeFilter: ATTRS
    });
    apply(lang);

    window.ExpoI18n = { t, translate };
})();
