/* Incident management: selection and explicit confirmation only. */
(function () {
    "use strict";
    const form = document.getElementById("incident-management-form");
    if (!form) return;
    const checkboxes = [...form.querySelectorAll('input[name="incident_ids"]')];
    const all = document.getElementById("select-all-incidents");
    if (all) all.addEventListener("change", () => checkboxes.forEach(box => { box.checked = all.checked; }));
    form.addEventListener("submit", event => {
        const button = event.submitter;
        if (!button) { event.preventDefault(); return; }
        if (button.hasAttribute("data-require-selection") && !checkboxes.some(box => box.checked)) {
            event.preventDefault();
            window.alert(window.ExpoI18n ? window.ExpoI18n.t("Select at least one incident.") : "Select at least one incident.");
            return;
        }
        const question = button.dataset.manageConfirm;
        if (question && !window.confirm(question)) event.preventDefault();
    });
})();
