const state = {
    csrfToken: readCookie("admin_csrf"),
    employerKey: null,
    username: null,
    view: "overview",
    config: null,
    contentResource: "assessments",
    editingItem: null,
    editingJobPosting: null,
    decision: null,
    answeringQuestion: null,
    questionStatus: "pending",
    questionPage: 1,
    processingStatus: "failed",
    processingPage: 1,
    auditOutcome: "",
    auditPage: 1,
    hygienePage: 1,
    hygieneWorkers: [],
    correctingWorker: null,
    cleaningWorker: null,
};

const viewMeta = {
    overview: ["OPERASYON", "Genel Bakış"],
    workers: ["EKİP", "Çalışanlar"],
    processing: ["OPERASYON", "Video İşleme"],
    jobs: ["İŞE ALIM", "İş İlanları"],
    applications: ["İŞE ALIM", "Başvurular"],
    questions: ["DESTEK", "Çalışan Soruları"],
    shuttle: ["ULAŞIM", "Servis Talepleri"],
    content: ["İÇERİK", "İçerik Yönetimi"],
    hygiene: ["OPERASYON", "Veri Kalitesi"],
    audit: ["GÜVENLİK", "Denetim Kaydı"],
};

const statusLabels = {
    submitted: "Yeni başvuru",
    reviewing: "İnceleniyor",
    shortlisted: "Kısa liste",
    rejected: "Reddedildi",
    hired: "İşe alındı",
    withdrawn: "Çalışan geri çekti",
    requested: "Onay bekliyor",
    confirmed: "Onaylandı",
    completed: "Tamamlandı",
    available: "Yayında",
    draft: "Taslak",
    archived: "Arşivde",
    published: "Yayında",
    closed: "Kapalı",
    profile_ready: "Profil hazır",
    registered: "Kayıtlı",
    not_uploaded: "Video bekleniyor",
    uploaded: "Yüklendi",
    queued: "İşlem sırasında",
    processing: "İşleniyor",
    failed: "Başarısız",
    replaced: "Değiştirildi",
    cancelled: "Çalışan iptal etti",
    pending: "Yanıt bekliyor",
    answered: "Yanıtlandı",
    auto_answered: "Otomatik yanıtlandı",
};

const contentMeta = {
    assessments: {
        label: "Değerlendirmeler",
        singular: "Değerlendirme",
        key: "assessments",
        path: "assessments",
    },
    trainings: {
        label: "Eğitimler",
        singular: "Eğitim",
        key: "trainings",
        path: "trainings",
    },
    "useful-info": {
        label: "Faydalı Bilgiler",
        singular: "Bilgi",
        key: "usefulInfo",
        path: "useful-info",
    },
    "qa-knowledge": {
        label: "Soru-Cevap",
        singular: "Cevap",
        key: "qaKnowledgeBase",
        path: "qa-knowledge",
    },
    "shuttle-routes": {
        label: "Servis Rotaları",
        singular: "Rota",
        key: "shuttleRoutes",
        path: "shuttle/routes",
    },
};

document.addEventListener("DOMContentLoaded", initialize);

function initialize() {
    sessionStorage.removeItem("adminToken");
    sessionStorage.removeItem("adminEmployerKey");
    sessionStorage.removeItem("adminUsername");
    document.getElementById("login-form").addEventListener("submit", login);
    document.getElementById("logout-button").addEventListener("click", logout);
    document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
        button.addEventListener("click", () => switchView(button.dataset.view));
    });
    document.querySelectorAll("[data-close-dialog]").forEach((button) => {
        button.addEventListener("click", () => {
            document.getElementById(button.dataset.closeDialog).close();
        });
    });
    document.getElementById("item-form").addEventListener("submit", saveContentItem);
    document.getElementById("decision-form").addEventListener("submit", saveDecision);
    document.getElementById("decision-status").addEventListener("change", syncDecisionInterviewFields);
    document.getElementById("interview-clear").addEventListener("change", syncDecisionInterviewFields);
    document.getElementById("invite-form").addEventListener("submit", saveWorkerInvitation);
    document.getElementById("job-form").addEventListener("submit", saveJobPosting);
    document.getElementById("question-form").addEventListener("submit", saveQuestionAnswer);
    document.getElementById("phone-correction-form").addEventListener("submit", savePhoneCorrection);
    document.getElementById("legacy-cleanup-form").addEventListener("submit", saveLegacyWorkerCleanup);
    document.getElementById("view-root").addEventListener("click", (event) => {
        const workerButton = event.target.closest?.("[data-worker-id]");
        if (workerButton) {
            openWorkerDetail(workerButton.dataset.workerId);
        }
    });

    if (state.csrfToken) {
        restoreSession();
    } else {
        showLogin();
    }
}

async function restoreSession() {
    try {
        const response = await api("/api/auth/me");
        if (response.principal.role !== "employer") {
            throw new Error("İşveren oturumu gerekli.");
        }
        state.csrfToken = readCookie("admin_csrf");
        state.employerKey = response.principal.employerKey;
        state.username = response.principal.username;
        showApp();
        await loadCurrentView();
    } catch (error) {
        clearSession();
        showLogin(error.message);
    }
}

async function login(event) {
    event.preventDefault();
    const errorElement = document.getElementById("login-error");
    const submitButton = event.currentTarget.querySelector("button[type=submit]");
    errorElement.textContent = "";
    submitButton.disabled = true;

    try {
        const response = await api("/api/admin/auth/login", {
            method: "POST",
            auth: false,
            body: {
                username: document.getElementById("username").value.trim(),
                password: document.getElementById("password").value,
            },
        });
        state.csrfToken = readCookie("admin_csrf");
        if (!state.csrfToken) {
            throw new Error("Güvenli yönetim oturumu başlatılamadı.");
        }
        state.employerKey = response.admin.employerKey;
        state.username = response.admin.username;
        document.getElementById("password").value = "";
        showApp();
        await loadCurrentView();
    } catch (error) {
        errorElement.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

async function logout() {
    try {
        await api("/api/auth/logout", {method: "POST"});
    } catch (_) {
        // The local session must still be cleared if the server token expired.
    }
    clearSession();
    showLogin();
}

function clearSession() {
    state.csrfToken = null;
    state.employerKey = null;
    state.username = null;
    state.config = null;
    sessionStorage.removeItem("adminToken");
    sessionStorage.removeItem("adminEmployerKey");
    sessionStorage.removeItem("adminUsername");
}

function showLogin(message = "") {
    document.getElementById("admin-app").hidden = true;
    document.getElementById("login-view").hidden = false;
    document.getElementById("login-error").textContent = message;
}

function showApp() {
    document.getElementById("login-view").hidden = true;
    document.getElementById("admin-app").hidden = false;
    document.getElementById("sidebar-employer").textContent = state.employerKey;
    document.getElementById("employer-badge").textContent = state.employerKey;
}

async function switchView(view) {
    if (!viewMeta[view] || state.view === view) return;
    state.view = view;
    document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
        button.classList.toggle("active", button.dataset.view === view);
    });
    await loadCurrentView();
}

async function loadCurrentView() {
    const [eyebrow, title] = viewMeta[state.view];
    document.getElementById("view-eyebrow").textContent = eyebrow;
    document.getElementById("view-title").textContent = title;
    setLoading(true);

    try {
        if (state.view === "overview") await renderOverview();
        if (state.view === "workers") await renderWorkers();
        if (state.view === "processing") await renderVideoProcessingJobs();
        if (state.view === "jobs") await renderJobPostings();
        if (state.view === "applications") await renderApplications();
        if (state.view === "questions") await renderQuestions();
        if (state.view === "shuttle") await renderShuttleRequests();
        if (state.view === "content") await renderContent();
        if (state.view === "hygiene") await renderDataHygiene();
        if (state.view === "audit") await renderAuditEvents();
        setError("");
    } catch (error) {
        setError(error.message);
    } finally {
        setLoading(false);
    }
}

async function renderOverview() {
    const data = await api("/api/admin/overview");
    const metrics = [
        ["Toplam çalışan", data.metrics.workers],
        ["Yayındaki ilan", data.metrics.publishedJobPostings],
        ["Açık başvuru", data.metrics.openApplications],
        ["Bekleyen servis", data.metrics.pendingShuttleRequests],
        ["Bekleyen soru", data.metrics.pendingQuestions],
        ["Tamamlanan eğitim", data.metrics.completedTrainings],
        ["Geçersiz telefon", data.metrics.invalidPhoneWorkers],
    ];
    document.getElementById("view-root").innerHTML = `
        <div class="metrics-grid">
            ${metrics.map(([label, value]) => `
                <article class="metric-card"><span>${escapeHtml(label)}</span><strong>${value}</strong></article>
            `).join("")}
        </div>
        ${operationsPanel(data.operations)}
        <div class="two-column">
            <section class="panel">
                <header class="panel-header"><div><h2>Son başvurular</h2><p>En yeni 5 aday başvurusu</p></div></header>
                ${applicationTable(data.recentApplications, false)}
            </section>
            <section class="panel">
                <header class="panel-header"><div><h2>İçerik durumu</h2><p>Çalışan uygulamasında yayınlanan içerikler</p></div></header>
                <div class="table-wrap">
                    <table><tbody>
                        ${contentCountRow("Değerlendirmeler", data.contentCounts.assessments)}
                        ${contentCountRow("Eğitimler", data.contentCounts.trainings)}
                        ${contentCountRow("Faydalı bilgiler", data.contentCounts.usefulInfo)}
                        ${contentCountRow("Soru-cevap kayıtları", data.contentCounts.qaKnowledgeBase)}
                        ${contentCountRow("Servis rotaları", data.contentCounts.shuttleRoutes)}
                    </tbody></table>
                </div>
            </section>
        </div>
    `;
    document.getElementById("inspect-video-jobs").addEventListener(
        "click",
        () => switchView("processing"),
    );
}

function operationsPanel(operations) {
    const video = operations.videoProcessing;
    const push = operations.pushNotifications;
    const videoRuntime = videoWorkerRuntimeLabel(video.runtime);
    const pushRuntime = pushWorkerRuntimeLabel(push.runtime, push.provider);
    const videoRuntimeInvalid = video.runtime?.transcriptionProvider === "faster_whisper"
        && video.runtime?.modelWarmed !== true;
    const pushRuntimeInvalid = push.provider === "fcm"
        && push.runtime?.credentialsValidated !== true;
    const videoStatus = video.queue.failed > 0
        || video.activeWorkers < 1
        || videoRuntimeInvalid
        ? "failed"
        : video.queue.queued > 0 || video.queue.processing > 0
            ? "processing"
            : "completed";
    const pushStatus = push.provider === "disabled"
        ? "disabled"
        : push.queue.failed > 0
            || push.activeWorkers < 1
            || pushRuntimeInvalid
            ? "failed"
            : push.queue.queued > 0 || push.queue.processing > 0
                ? "processing"
                : "completed";
    const sourceStatus = operations.videoSourceDeletionFailures > 0
        ? "failed"
        : "completed";

    return `
        <section class="panel operations-panel">
            <header class="panel-header">
                <div><h2>İşlem durumu</h2><p>Çalışan profilleri ve bildirim kuyrukları</p></div>
                <button id="inspect-video-jobs" class="button secondary small" type="button">Video işlerini incele</button>
            </header>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Hizmet</th><th>Durum</th><th>Bekleyen</th><th>İşleniyor</th><th>Başarısız</th><th>Aktif worker</th></tr></thead>
                    <tbody>
                        <tr>
                            <td><span class="cell-title">Video profil işleme</span><span class="cell-subtitle">${escapeHtml(videoRuntime)}</span></td>
                            <td>${operationStatusBadge(videoStatus)}</td>
                            <td>${video.queue.queued}</td>
                            <td>${video.queue.processing}</td>
                            <td>${video.queue.failed}</td>
                            <td>${video.activeWorkers}</td>
                        </tr>
                        <tr>
                            <td><span class="cell-title">Push bildirimleri</span><span class="cell-subtitle">${escapeHtml(pushRuntime)}</span></td>
                            <td>${operationStatusBadge(pushStatus)}</td>
                            <td>${push.queue.queued}</td>
                            <td>${push.queue.processing}</td>
                            <td>${push.queue.failed}</td>
                            <td>${push.activeWorkers}</td>
                        </tr>
                        <tr>
                            <td><span class="cell-title">Video kaynak temizliği</span></td>
                            <td>${operationStatusBadge(sourceStatus)}</td>
                            <td>-</td>
                            <td>-</td>
                            <td>${operations.videoSourceDeletionFailures}</td>
                            <td>-</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    `;
}

function videoWorkerRuntimeLabel(runtime) {
    if (!runtime) return "Aktif worker heartbeat bekleniyor";
    const provider = runtime.transcriptionProvider || "provider bilinmiyor";
    const model = runtime.transcriptionModel ? ` / ${runtime.transcriptionModel}` : "";
    const readiness = runtime.modelWarmed === true
        ? "model hazır"
        : "model doğrulanmadı";
    return `${provider}${model} · ${readiness}`;
}

function pushWorkerRuntimeLabel(runtime, configuredProvider) {
    if (!runtime) {
        return configuredProvider === "disabled"
            ? "Devre dışı"
            : `${configuredProvider} · aktif worker heartbeat bekleniyor`;
    }
    const provider = runtime.provider || configuredProvider || "provider bilinmiyor";
    const project = runtime.projectId ? ` / ${runtime.projectId}` : "";
    const readiness = runtime.credentialsValidated === true
        ? "kimlik doğrulandı"
        : provider === "fcm"
            ? "kimlik doğrulanmadı"
            : "yerel provider";
    return `${provider}${project} · ${readiness}`;
}

function operationStatusBadge(status) {
    const labels = {
        completed: "Hazır",
        processing: "İşlem var",
        failed: "Müdahale gerekli",
        disabled: "Devre dışı",
    };
    return `<span class="status-badge ${escapeAttribute(status)}">${escapeHtml(labels[status] || status)}</span>`;
}

async function renderVideoProcessingJobs(
    status = state.processingStatus,
    page = state.processingPage,
) {
    state.processingStatus = status;
    state.processingPage = page;
    const params = new URLSearchParams({
        page: String(page),
        limit: "25",
    });
    if (status) params.set("status", status);
    const data = await api(
        `/api/employers/${encodeURIComponent(state.employerKey)}/video-processing-jobs?${params}`,
    );
    document.getElementById("view-root").innerHTML = `
        <div class="toolbar">
            <div class="toolbar-group">
                <select id="processing-filter" aria-label="Video işleme durumu">
                    <option value="">Tüm durumlar</option>
                    ${["failed", "queued", "processing", "completed"].map((value) => `
                        <option value="${value}" ${status === value ? "selected" : ""}>${statusLabel(value)}</option>
                    `).join("")}
                </select>
            </div>
            <span class="employer-badge">${data.pagination.total} işlem</span>
        </div>
        <section class="panel">
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Çalışan</th><th>Video</th><th>Durum</th><th>Deneme</th><th>Son hata</th><th>Güncelleme</th><th></th></tr></thead>
                    <tbody>
                        ${data.videoProcessingJobs.length
                            ? data.videoProcessingJobs.map(videoProcessingJobRow).join("")
                            : emptyTableRow(7, "Video işleme kaydı bulunamadı.")}
                    </tbody>
                </table>
            </div>
        </section>
        ${paginationControls(data.pagination)}
    `;
    document.getElementById("processing-filter").addEventListener(
        "change",
        (event) => renderVideoProcessingJobs(event.currentTarget.value, 1),
    );
    document.querySelectorAll("[data-retry-video-job]").forEach((button) => {
        button.addEventListener(
            "click",
            () => retryVideoProcessingJob(button.dataset.retryVideoJob),
        );
    });
    bindPagination(
        (nextPage) => renderVideoProcessingJobs(status, nextPage),
    );
}

function videoProcessingJobRow(job) {
    return `
        <tr>
            <td>
                ${job.worker?.id
                    ? `<button class="cell-link" type="button" data-worker-id="${escapeAttribute(job.worker.id)}">${escapeHtml(job.worker.name || "İsim bekleniyor")}</button>`
                    : '<span class="cell-title">Çalışan bulunamadı</span>'}
                <span class="cell-subtitle">${escapeHtml(job.worker?.phone || shortId(job.userId))}</span>
            </td>
            <td><span class="cell-title">${escapeHtml(job.video?.originalFilename || shortId(job.videoId))}</span></td>
            <td>${statusBadge(job.status)}</td>
            <td>${job.attempts} / ${job.maxAttempts ?? "-"}</td>
            <td><span class="cell-title question-copy">${escapeHtml(job.lastError || "-")}</span></td>
            <td>${formatDate(job.updatedAt)}</td>
            <td>
                ${job.status === "failed"
                    ? `<button class="button secondary small" type="button" data-retry-video-job="${escapeAttribute(job.id)}">Yeniden kuyruğa al</button>`
                    : ""}
            </td>
        </tr>
    `;
}

async function retryVideoProcessingJob(jobId) {
    const button = document.querySelector(
        `[data-retry-video-job="${CSS.escape(jobId)}"]`,
    );
    if (button) button.disabled = true;
    try {
        await api(
            `/api/employers/${encodeURIComponent(state.employerKey)}/video-processing-jobs/${encodeURIComponent(jobId)}/retry`,
            {method: "POST"},
        );
        showToast("Video işleme işi yeniden kuyruğa alındı.");
        await renderVideoProcessingJobs(
            state.processingStatus,
            state.processingPage,
        );
    } catch (error) {
        showToast(error.message);
        if (button) button.disabled = false;
    }
}

async function renderWorkers(search = "", page = 1) {
    const params = new URLSearchParams({page: String(page), limit: "25"});
    if (search) params.set("search", search);
    const [data, invitationData] = await Promise.all([
        api(`/api/employers/${encodeURIComponent(state.employerKey)}/workers?${params}`),
        api(`/api/employers/${encodeURIComponent(state.employerKey)}/worker-invitations?status=pending`),
    ]);
    document.getElementById("view-root").innerHTML = `
        <div class="toolbar">
            <div class="toolbar-group">
                <input id="worker-search" type="search" value="${escapeAttribute(search)}" placeholder="Ad veya telefon ara">
                <button id="worker-search-button" class="button secondary" type="button">Ara</button>
            </div>
            <div class="toolbar-group">
                <span class="employer-badge">${data.pagination.total} çalışan</span>
                <button id="invite-worker-button" class="button primary" type="button">Çalışan davet et</button>
            </div>
        </div>
        <section class="panel">
            <header class="panel-header"><div><h2>Çalışanlar</h2><p>Telefonunu doğrulamış işveren çalışanları</p></div></header>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Çalışan</th><th>Profil</th><th>Beceriler</th><th>Başvuru</th><th>Kayıt</th><th></th></tr></thead>
                    <tbody>
                        ${data.workers.length ? data.workers.map(workerRow).join("") : emptyTableRow(6, "Çalışan bulunamadı.")}
                    </tbody>
                </table>
            </div>
        </section>
        ${paginationControls(data.pagination)}
        <section class="panel invitation-panel">
            <header class="panel-header"><div><h2>Bekleyen davetler</h2><p>Henüz telefon doğrulamasını tamamlamayan çalışanlar</p></div></header>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Telefon</th><th>Oluşturan</th><th>Oluşturulma</th><th>Son geçerlilik</th><th></th></tr></thead>
                    <tbody>
                        ${invitationData.workerInvitations.length ? invitationData.workerInvitations.map(invitationRow).join("") : emptyTableRow(5, "Bekleyen davet bulunmuyor.")}
                    </tbody>
                </table>
            </div>
        </section>
    `;
    document.getElementById("worker-search-button").addEventListener("click", () => {
        renderWorkers(document.getElementById("worker-search").value.trim());
    });
    document.getElementById("worker-search").addEventListener("keydown", (event) => {
        if (event.key === "Enter") renderWorkers(event.currentTarget.value.trim());
    });
    document.getElementById("invite-worker-button").addEventListener("click", openWorkerInvitation);
    document.querySelectorAll("[data-cancel-invitation]").forEach((button) => {
        button.addEventListener("click", () => cancelWorkerInvitation(button.dataset.cancelInvitation));
    });
    bindPagination((nextPage) => renderWorkers(search, nextPage));
}

async function renderDataHygiene(page = state.hygienePage) {
    state.hygienePage = page;
    const params = new URLSearchParams({
        page: String(page),
        limit: "25",
    });
    const data = await api(
        `/api/employers/${encodeURIComponent(state.employerKey)}/data-hygiene/workers?${params}`,
    );
    state.hygieneWorkers = data.workers;
    document.getElementById("view-root").innerHTML = `
        <section class="panel">
            <header class="panel-header">
                <div>
                    <h2>Geçersiz telefon kayıtları</h2>
                    <p>Production health kontrolünü durduran eski ve eksik telefon kayıtları</p>
                </div>
                <span class="employer-badge">${data.pagination.total} kayıt</span>
            </header>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr><th>Çalışan</th><th>Güvenlik</th><th>Bağlı kayıtlar</th><th>Kayıt</th><th></th></tr>
                    </thead>
                    <tbody>
                        ${data.workers.length
                            ? data.workers.map(dataHygieneWorkerRow).join("")
                            : emptyTableRow(5, "Geçersiz telefon kaydı bulunmuyor.")}
                    </tbody>
                </table>
            </div>
        </section>
        ${paginationControls(data.pagination)}
    `;
    document.querySelectorAll("[data-correct-phone]").forEach((button) => {
        button.addEventListener("click", () => {
            const worker = state.hygieneWorkers.find(
                (item) => item.id === button.dataset.correctPhone,
            );
            if (worker) openPhoneCorrection(worker);
        });
    });
    document.querySelectorAll("[data-cleanup-worker]").forEach((button) => {
        button.addEventListener("click", () => {
            const worker = state.hygieneWorkers.find(
                (item) => item.id === button.dataset.cleanupWorker,
            );
            if (worker) openLegacyWorkerCleanup(worker);
        });
    });
    bindPagination((nextPage) => renderDataHygiene(nextPage));
}

function dataHygieneWorkerRow(worker) {
    const security = [
        worker.phoneVerifiedAt ? "Telefon doğrulanmış" : "Telefon doğrulanmamış",
        `${worker.authSessionCount} oturum`,
        `${worker.videoCount} video`,
    ].join(" · ");
    const related = [
        `${worker.applicationCount} başvuru`,
        `${worker.supportRecordCount} destek kaydı`,
    ].join(" · ");
    const blockerText = hygieneBlockerLabels(
        [...new Set([
            ...(worker.correctionBlockers || []),
            ...(worker.cleanupBlockers || []),
        ])],
    );
    return `
        <tr>
            <td>
                <span class="cell-title">${escapeHtml(worker.name || "İsim bekleniyor")}</span>
                <span class="cell-subtitle">${escapeHtml(worker.phone || "-")}</span>
            </td>
            <td>
                <span class="cell-title">${escapeHtml(security)}</span>
                ${blockerText ? `<span class="cell-subtitle">${escapeHtml(blockerText)}</span>` : ""}
            </td>
            <td>${escapeHtml(related)}</td>
            <td>${formatDate(worker.createdAt)}</td>
            <td>
                <div class="actions">
                    <button class="button secondary small" type="button" data-correct-phone="${escapeAttribute(worker.id)}" ${worker.canCorrectPhone ? "" : "disabled"}>Düzelt</button>
                    <button class="button danger small" type="button" data-cleanup-worker="${escapeAttribute(worker.id)}" ${worker.canCleanup ? "" : "disabled"}>Temizle</button>
                </div>
            </td>
        </tr>`;
}

function hygieneBlockerLabels(blockers) {
    const labels = {
        phone_valid: "Telefon zaten geçerli",
        phone_verified: "Telefon doğrulanmış",
        auth_sessions: "Oturum kaydı var",
        videos: "Video kaydı var",
    };
    return blockers.map((value) => labels[value] || value).join(" · ");
}

function openPhoneCorrection(worker) {
    state.correctingWorker = worker;
    document.getElementById("phone-correction-context").textContent =
        `${worker.name || "İsimsiz çalışan"} · ${worker.phone || "-"}`;
    document.getElementById("corrected-phone").value = "";
    document.getElementById("phone-correction-error").textContent = "";
    document.getElementById("phone-correction-dialog").showModal();
}

async function savePhoneCorrection(event) {
    event.preventDefault();
    const worker = state.correctingWorker;
    if (!worker) return;
    const submitButton = event.currentTarget.querySelector("button[type=submit]");
    const errorElement = document.getElementById("phone-correction-error");
    submitButton.disabled = true;
    errorElement.textContent = "";
    try {
        await api(
            `/api/employers/${encodeURIComponent(state.employerKey)}/data-hygiene/workers/${encodeURIComponent(worker.id)}/phone`,
            {
                method: "PATCH",
                body: {
                    phone: document.getElementById("corrected-phone").value.trim(),
                },
            },
        );
        state.correctingWorker = null;
        document.getElementById("phone-correction-dialog").close();
        showToast("Telefon kaydı düzeltildi.");
        await renderDataHygiene();
    } catch (error) {
        errorElement.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

function openLegacyWorkerCleanup(worker) {
    state.cleaningWorker = worker;
    document.getElementById("legacy-cleanup-context").textContent =
        `${worker.name || "İsimsiz çalışan"} (${worker.phone || "-"}) kaydı temizlenecek.`;
    document.getElementById("legacy-cleanup-confirmation").value = "";
    document.getElementById("legacy-cleanup-error").textContent = "";
    document.getElementById("legacy-cleanup-dialog").showModal();
}

async function saveLegacyWorkerCleanup(event) {
    event.preventDefault();
    const worker = state.cleaningWorker;
    if (!worker) return;
    const submitButton = event.currentTarget.querySelector("button[type=submit]");
    const errorElement = document.getElementById("legacy-cleanup-error");
    submitButton.disabled = true;
    errorElement.textContent = "";
    try {
        await api(
            `/api/employers/${encodeURIComponent(state.employerKey)}/data-hygiene/workers/${encodeURIComponent(worker.id)}`,
            {
                method: "DELETE",
                body: {
                    confirmation: document.getElementById(
                        "legacy-cleanup-confirmation",
                    ).value,
                },
            },
        );
        state.cleaningWorker = null;
        document.getElementById("legacy-cleanup-dialog").close();
        showToast("Eski çalışan kaydı güvenli biçimde temizlendi.");
        await renderDataHygiene();
    } catch (error) {
        errorElement.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

function openWorkerInvitation() {
    document.getElementById("invite-phone").value = "";
    document.getElementById("invite-error").textContent = "";
    document.getElementById("invite-dialog").showModal();
}

async function saveWorkerInvitation(event) {
    event.preventDefault();
    const errorElement = document.getElementById("invite-error");
    const submitButton = event.currentTarget.querySelector("button[type=submit]");
    submitButton.disabled = true;
    errorElement.textContent = "";
    try {
        await api(`/api/employers/${encodeURIComponent(state.employerKey)}/worker-invitations`, {
            method: "POST",
            body: {phone: document.getElementById("invite-phone").value.trim()},
        });
        document.getElementById("invite-dialog").close();
        showToast("Çalışan daveti oluşturuldu.");
        await renderWorkers();
    } catch (error) {
        errorElement.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

async function cancelWorkerInvitation(invitationId) {
    try {
        await api(`/api/employers/${encodeURIComponent(state.employerKey)}/worker-invitations/${encodeURIComponent(invitationId)}`, {
            method: "DELETE",
        });
        showToast("Davet iptal edildi.");
        await renderWorkers();
    } catch (error) {
        setError(error.message);
    }
}

async function openWorkerDetail(workerId) {
    const dialog = document.getElementById("worker-detail-dialog");
    const title = document.getElementById("worker-detail-title");
    const body = document.getElementById("worker-detail-body");
    title.textContent = "Çalışan detayı";
    body.innerHTML = '<p class="state-message">Çalışan bilgileri yükleniyor...</p>';
    if (!dialog.open) dialog.showModal();

    try {
        const data = await api(
            `/api/employers/${encodeURIComponent(state.employerKey)}/workers/${encodeURIComponent(workerId)}`,
        );
        title.textContent = data.worker.name || "İsim bekleniyor";
        body.innerHTML = workerDetailMarkup(data);
        document.getElementById("worker-assignment-form")
            ?.addEventListener(
                "submit",
                (event) => saveWorkerSupportAssignments(
                    event,
                    workerId,
                ),
            );
    } catch (error) {
        body.innerHTML = `<p class="state-message error">${escapeHtml(error.message)}</p>`;
    }
}

async function saveWorkerSupportAssignments(event, workerId) {
    event.preventDefault();
    const form = event.currentTarget;
    const submitButton = form.querySelector("button[type=submit]");
    const message = form.querySelector("[data-assignment-message]");
    submitButton.disabled = true;
    message.textContent = "";

    try {
        await api(
            `/api/employers/${encodeURIComponent(state.employerKey)}/workers/${encodeURIComponent(workerId)}/support-assignments`,
            {
                method: "PUT",
                body: {
                    assessmentIds: [
                        ...form.querySelectorAll(
                            'input[name="assessmentIds"]:checked',
                        ),
                    ].map((input) => input.value),
                    trainingIds: [
                        ...form.querySelectorAll(
                            'input[name="trainingIds"]:checked',
                        ),
                    ].map((input) => input.value),
                },
            },
        );
        showToast("Çalışan içerikleri güncellendi.");
        await openWorkerDetail(workerId);
    } catch (error) {
        message.textContent = error.message;
        submitButton.disabled = false;
    }
}

function workerDetailMarkup(data) {
    const worker = data.worker;
    const profile = data.profile;
    const shuttle = data.shuttleRequest;
    const videoConsent = data.videoConsent;
    return `
        <section class="worker-detail-summary" aria-label="Çalışan özeti">
            <div>
                <span class="cell-title">${escapeHtml(worker.name || "İsim bekleniyor")}</span>
                <span class="cell-subtitle">${escapeHtml(worker.phone)}</span>
            </div>
            <div class="worker-detail-statuses">
                ${statusBadge(worker.profileStatus)}
                ${statusBadge(worker.videoStatus)}
                ${profileReviewBadge(worker.profileReviewStatus)}
            </div>
        </section>

        <section class="worker-detail-section">
            <h3>Aday profili</h3>
            ${profile ? `
                <p class="detail-copy">${escapeHtml(profile.summary || "Profil özeti bulunmuyor.")}</p>
                <dl class="detail-list">
                    <div><dt>Ad soyad</dt><dd>${escapeHtml(worker.name || profile.name || "-")}</dd></div>
                    <div><dt>Ad doğrulama</dt><dd>${profileReviewBadge(worker.profileReviewStatus)}</dd></div>
                    <div><dt>Video işleme onayı</dt><dd>${consentBadge(videoConsent)}</dd></div>
                    <div><dt>Tercih edilen roller</dt><dd>${escapeHtml((profile.preferredRoles || []).join(", ") || "-")}</dd></div>
                    <div><dt>Uygunluk</dt><dd>${escapeHtml(profile.availability || "-")}</dd></div>
                    <div><dt>Çıkarım güveni</dt><dd>${profile.confidence == null ? "-" : `%${Math.round(Number(profile.confidence) * 100)}`}</dd></div>
                </dl>
                <div class="detail-chip-list" aria-label="Beceriler">
                    ${(profile.skills || []).length
                        ? profile.skills.map((skill) => `<span class="detail-chip">${escapeHtml(skill)}</span>`).join("")
                        : '<span class="helper-text">Beceri çıkarımı bulunmuyor.</span>'}
                </div>
            ` : `
                <p class="detail-copy muted">Video CV işlendikten sonra aday profili burada görünecek.</p>
                <dl class="detail-list">
                    <div><dt>Video işleme onayı</dt><dd>${consentBadge(videoConsent)}</dd></div>
                </dl>
            `}
        </section>

        ${workerAssignmentMarkup(data.supportAssignments)}

        <div class="worker-detail-grid">
            <section class="worker-detail-section">
                <h3>Değerlendirmeler</h3>
                ${data.assessmentResults.length ? `
                    <ul class="detail-record-list">
                        ${data.assessmentResults.map((item) => `
                            <li>
                                <div><strong>${escapeHtml(item.title || item.assessmentId)}</strong><span>${formatDate(item.completedAt)}</span></div>
                                <span class="result-label ${item.passed ? "passed" : "failed"}">%${item.score ?? "-"} · ${item.passed ? "Geçti" : "Kaldı"} · ${item.attemptCount || 1}. deneme</span>
                            </li>
                        `).join("")}
                    </ul>
                ` : '<p class="detail-copy muted">Tamamlanan değerlendirme yok.</p>'}
            </section>
            <section class="worker-detail-section">
                <h3>Eğitimler</h3>
                ${data.trainingProgress.length ? `
                    <ul class="detail-record-list">
                        ${data.trainingProgress.map((item) => `
                            <li>
                                <div><strong>${escapeHtml(item.title || item.trainingId)}</strong><span>${formatDate(item.completedAt)}</span></div>
                                <span class="result-label passed">%${item.progressPercent ?? 0}</span>
                            </li>
                        `).join("")}
                    </ul>
                ` : '<p class="detail-copy muted">Tamamlanan eğitim yok.</p>'}
            </section>
        </div>

        <section class="worker-detail-section">
            <h3>Servis durumu</h3>
            ${shuttle ? `
                <dl class="detail-list">
                    <div><dt>Rota</dt><dd>${escapeHtml(shuttle.routeName || shuttle.routeId || "-")}</dd></div>
                    <div><dt>Alım aralığı</dt><dd>${escapeHtml(shuttle.pickupWindow || "-")}</dd></div>
                    <div><dt>Durum</dt><dd>${statusBadge(shuttle.status)}</dd></div>
                    <div><dt>Çalışan notu</dt><dd>${escapeHtml(shuttle.pickupNote || "-")}</dd></div>
                    <div><dt>İşveren notu</dt><dd>${escapeHtml(shuttle.decisionNote || "-")}</dd></div>
                </dl>
            ` : '<p class="detail-copy muted">Servis talebi bulunmuyor.</p>'}
        </section>

        <section class="worker-detail-section">
            <h3>Son sorular</h3>
            ${data.recentQuestions.length ? `
                <ul class="detail-question-list">
                    ${data.recentQuestions.map((item) => `
                        <li>
                            <div><strong>${escapeHtml(item.question)}</strong>${statusBadge(item.status)}</div>
                            <p>${escapeHtml(item.answer || "Henüz yanıtlanmadı.")}</p>
                            <span>${formatDate(item.createdAt)}</span>
                        </li>
                    `).join("")}
                </ul>
            ` : '<p class="detail-copy muted">Çalışan henüz soru sormadı.</p>'}
        </section>

        <section class="worker-detail-section">
            <h3>İş başvuruları</h3>
            ${applicationTable(data.applications, false)}
        </section>
    `;
}

function workerAssignmentMarkup(assignments) {
    const selectedAssessments = new Set(
        assignments?.assessmentIds || [],
    );
    const selectedTrainings = new Set(
        assignments?.trainingIds || [],
    );
    const assessmentCatalog =
        assignments?.catalog?.assessments || [];
    const trainingCatalog = assignments?.catalog?.trainings || [];
    const assignmentStatus = assignments?.customized
        ? "Özel atama"
        : "Yayındaki tüm içerikler";
    return `
        <section class="worker-detail-section">
            <div class="assignment-heading">
                <h3>Atanan içerikler</h3>
                <span class="status-badge available">${escapeHtml(assignmentStatus)}</span>
            </div>
            <form id="worker-assignment-form" class="assignment-form">
                <fieldset>
                    <legend>Değerlendirmeler</legend>
                    <div class="assignment-options">
                        ${assessmentCatalog.length
                            ? assessmentCatalog.map((item) => assignmentOption(
                                "assessmentIds",
                                item,
                                selectedAssessments.has(item.id),
                            )).join("")
                            : '<p class="detail-copy muted">Yayında değerlendirme yok.</p>'}
                    </div>
                </fieldset>
                <fieldset>
                    <legend>Eğitimler</legend>
                    <div class="assignment-options">
                        ${trainingCatalog.length
                            ? trainingCatalog.map((item) => assignmentOption(
                                "trainingIds",
                                item,
                                selectedTrainings.has(item.id),
                            )).join("")
                            : '<p class="detail-copy muted">Yayında eğitim yok.</p>'}
                    </div>
                </fieldset>
                <div class="assignment-actions">
                    <p class="form-error" data-assignment-message role="alert"></p>
                    <button class="button primary small" type="submit">Atamaları kaydet</button>
                </div>
            </form>
        </section>`;
}

function assignmentOption(name, item, checked) {
    const detail = [
        item.durationMinutes
            ? `${item.durationMinutes} dk`
            : null,
        item.required ? "Zorunlu" : null,
    ].filter(Boolean).join(" · ");
    return `
        <label class="assignment-option">
            <input
                type="checkbox"
                name="${escapeAttribute(name)}"
                value="${escapeAttribute(item.id)}"
                ${checked ? "checked" : ""}
            >
            <span>
                <strong>${escapeHtml(item.title || item.id)}</strong>
                ${detail ? `<small>${escapeHtml(detail)}</small>` : ""}
            </span>
        </label>`;
}

async function renderJobPostings(status = "", page = 1) {
    const params = new URLSearchParams({page: String(page), limit: "25"});
    if (status) params.set("status", status);
    const data = await api(`/api/employers/${encodeURIComponent(state.employerKey)}/job-postings?${params}`);
    document.getElementById("view-root").innerHTML = `
        <div class="toolbar">
            <div class="toolbar-group">
                <select id="job-filter" aria-label="İlan durumu">
                    <option value="">Tüm durumlar</option>
                    ${["draft", "published", "closed"].map((value) => `
                        <option value="${value}" ${status === value ? "selected" : ""}>${statusLabel(value)}</option>
                    `).join("")}
                </select>
            </div>
            <div class="toolbar-group">
                <span class="employer-badge">${data.pagination.total} ilan</span>
                <button id="add-job-button" class="button primary" type="button">İlan ekle</button>
            </div>
        </div>
        <section class="panel">
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Pozisyon</th><th>Çalışma</th><th>Beceriler</th><th>Kontenjan</th><th>Başvuru</th><th>Durum</th><th></th></tr></thead>
                    <tbody>
                        ${data.jobPostings.length ? data.jobPostings.map(jobPostingRow).join("") : emptyTableRow(7, "İş ilanı bulunamadı.")}
                    </tbody>
                </table>
            </div>
        </section>
        ${paginationControls(data.pagination)}
    `;
    document.getElementById("job-filter").addEventListener("change", (event) => {
        renderJobPostings(event.currentTarget.value);
    });
    document.getElementById("add-job-button").addEventListener("click", () => openJobDialog(null));
    document.querySelectorAll("[data-edit-job]").forEach((button) => {
        button.addEventListener("click", () => {
            const posting = data.jobPostings.find((item) => item.id === button.dataset.editJob);
            openJobDialog(posting);
        });
    });
    document.querySelectorAll("[data-job-status]").forEach((button) => {
        button.addEventListener("click", () => updateJobPostingStatus(
            button.dataset.jobStatus,
            button.dataset.nextStatus,
        ));
    });
    document.querySelectorAll("[data-delete-job]").forEach((button) => {
        button.addEventListener("click", () => deleteJobPosting(button.dataset.deleteJob));
    });
    bindPagination((nextPage) => renderJobPostings(status, nextPage));
}

function openJobDialog(posting) {
    state.editingJobPosting = posting || null;
    document.getElementById("job-dialog-title").textContent = posting ? "İlanı düzenle" : "İlan ekle";
    document.getElementById("job-form-error").textContent = "";
    document.getElementById("job-title").value = posting?.title || "";
    document.getElementById("job-company").value = posting?.company || state.employerKey || "";
    document.getElementById("job-location").value = posting?.location || "";
    document.getElementById("job-openings").value = posting?.openings || 1;
    document.getElementById("job-employment-type").value = posting?.employmentType || "full_time";
    document.getElementById("job-shift").value = posting?.shift || "day";
    document.getElementById("job-status").value = posting?.status || "draft";
    document.getElementById("job-description").value = posting?.description || "";
    document.getElementById("job-required-skills").value = (posting?.requiredSkills || []).join(", ");
    document.getElementById("job-optional-skills").value = (posting?.optionalSkills || []).join(", ");
    document.getElementById("job-dialog").showModal();
}

async function saveJobPosting(event) {
    event.preventDefault();
    const errorElement = document.getElementById("job-form-error");
    const submitButton = event.currentTarget.querySelector("button[type=submit]");
    const postingId = state.editingJobPosting?.id;
    errorElement.textContent = "";
    submitButton.disabled = true;
    try {
        await api(
            `/api/employers/${encodeURIComponent(state.employerKey)}/job-postings${postingId ? `/${encodeURIComponent(postingId)}` : ""}`,
            {
                method: postingId ? "PATCH" : "POST",
                body: {
                    title: document.getElementById("job-title").value.trim(),
                    company: document.getElementById("job-company").value.trim(),
                    location: document.getElementById("job-location").value.trim(),
                    description: document.getElementById("job-description").value.trim(),
                    requiredSkills: commaSeparatedValues(document.getElementById("job-required-skills").value),
                    optionalSkills: commaSeparatedValues(document.getElementById("job-optional-skills").value),
                    status: document.getElementById("job-status").value,
                    employmentType: document.getElementById("job-employment-type").value,
                    shift: document.getElementById("job-shift").value,
                    openings: Number(document.getElementById("job-openings").value),
                },
            },
        );
        document.getElementById("job-dialog").close();
        showToast(postingId ? "İlan güncellendi." : "İlan oluşturuldu.");
        await renderJobPostings();
    } catch (error) {
        errorElement.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

async function updateJobPostingStatus(postingId, status) {
    try {
        await api(`/api/employers/${encodeURIComponent(state.employerKey)}/job-postings/${encodeURIComponent(postingId)}`, {
            method: "PATCH",
            body: {status},
        });
        showToast(status === "published" ? "İlan yayınlandı." : "İlan kapatıldı.");
        await renderJobPostings();
    } catch (error) {
        setError(error.message);
    }
}

async function deleteJobPosting(postingId) {
    if (!window.confirm("İş ilanı silinsin mi? Başvuru alınmış ilanlar yalnızca kapatılabilir.")) return;
    try {
        await api(`/api/employers/${encodeURIComponent(state.employerKey)}/job-postings/${encodeURIComponent(postingId)}`, {
            method: "DELETE",
        });
        showToast("İlan silindi.");
        await renderJobPostings();
    } catch (error) {
        showToast(error.message);
    }
}

async function renderApplications(status = "", page = 1) {
    const params = new URLSearchParams({page: String(page), limit: "25"});
    if (status) params.set("status", status);
    const data = await api(`/api/employers/${encodeURIComponent(state.employerKey)}/job-applications?${params}`);
    document.getElementById("view-root").innerHTML = `
        <div class="toolbar">
            <div class="toolbar-group">
                <select id="application-filter" aria-label="Başvuru durumu">
                    ${statusOptions(status, true)}
                </select>
            </div>
            <span class="employer-badge">${data.pagination.total} başvuru</span>
        </div>
        <section class="panel">${applicationTable(data.jobApplications, true)}</section>
        ${paginationControls(data.pagination)}
    `;
    document.getElementById("application-filter").addEventListener("change", (event) => {
        renderApplications(event.currentTarget.value);
    });
    document.querySelectorAll("[data-application-id]").forEach((button) => {
        button.addEventListener("click", () => {
            const application = data.jobApplications.find(
                (item) => item.id === button.dataset.applicationId,
            );
            openApplicationDecision(application);
        });
    });
    bindPagination((nextPage) => renderApplications(status, nextPage));
}

async function renderQuestions(status = state.questionStatus, page = 1) {
    state.questionStatus = status;
    state.questionPage = page;
    const params = new URLSearchParams({page: String(page), limit: "25"});
    if (status) params.set("status", status);
    const data = await api(`/api/employers/${encodeURIComponent(state.employerKey)}/questions?${params}`);
    document.getElementById("view-root").innerHTML = `
        <div class="toolbar">
            <div class="toolbar-group">
                <select id="question-filter" aria-label="Soru durumu">
                    <option value="" ${status === "" ? "selected" : ""}>Tüm durumlar</option>
                    ${["pending", "answered", "auto_answered"].map((value) => `
                        <option value="${value}" ${status === value ? "selected" : ""}>${statusLabel(value)}</option>
                    `).join("")}
                </select>
            </div>
            <span class="employer-badge">${data.pagination.total} soru</span>
        </div>
        <section class="panel">
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Çalışan</th><th>Soru</th><th>Yanıt</th><th>Durum</th><th>Tarih</th><th></th></tr></thead>
                    <tbody>
                        ${data.questions.length ? data.questions.map(questionRow).join("") : emptyTableRow(6, "Bu durumda soru bulunamadı.")}
                    </tbody>
                </table>
            </div>
        </section>
        ${paginationControls(data.pagination)}
    `;
    document.getElementById("question-filter").addEventListener("change", (event) => {
        renderQuestions(event.currentTarget.value);
    });
    document.querySelectorAll("[data-answer-question]").forEach((button) => {
        button.addEventListener("click", () => {
            const question = data.questions.find((item) => item.id === button.dataset.answerQuestion);
            openQuestionDialog(question);
        });
    });
    bindPagination((nextPage) => renderQuestions(status, nextPage));
}

function questionRow(item) {
    return `
        <tr>
            <td><span class="cell-title">${escapeHtml(item.worker?.name || "İsim bekleniyor")}</span><span class="cell-subtitle">${escapeHtml(item.worker?.phone || shortId(item.userId))}</span></td>
            <td><span class="cell-title question-copy">${escapeHtml(item.question || "-")}</span></td>
            <td><span class="cell-title question-copy">${escapeHtml(item.answer || "-")}</span></td>
            <td>${statusBadge(item.status)}</td>
            <td>${formatDate(item.createdAt)}</td>
            <td><button class="button secondary small" type="button" data-answer-question="${escapeAttribute(item.id)}">${item.status === "pending" ? "Yanıtla" : "Düzenle"}</button></td>
        </tr>`;
}

function openQuestionDialog(question) {
    if (!question) return;
    state.answeringQuestion = question;
    document.getElementById("question-error").textContent = "";
    document.getElementById("question-context").innerHTML = `
        <strong>${escapeHtml(question.worker?.name || question.worker?.phone || "Çalışan")}</strong>
        <p>${escapeHtml(question.question || "")}</p>`;
    document.getElementById("question-answer").value = question.status === "pending" ? "" : (question.answer || "");
    document.getElementById("question-dialog").showModal();
}

async function saveQuestionAnswer(event) {
    event.preventDefault();
    if (!state.answeringQuestion?.id) return;
    const submitButton = event.currentTarget.querySelector("button[type=submit]");
    const errorElement = document.getElementById("question-error");
    submitButton.disabled = true;
    errorElement.textContent = "";
    try {
        await api(
            `/api/employers/${encodeURIComponent(state.employerKey)}/questions/${encodeURIComponent(state.answeringQuestion.id)}`,
            {
                method: "PATCH",
                body: {answer: document.getElementById("question-answer").value.trim()},
            },
        );
        document.getElementById("question-dialog").close();
        state.answeringQuestion = null;
        showToast("Yanıt çalışana iletildi.");
        await renderQuestions(state.questionStatus, state.questionPage);
    } catch (error) {
        errorElement.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

async function renderShuttleRequests(status = "", page = 1) {
    const params = new URLSearchParams({page: String(page), limit: "25"});
    if (status) params.set("status", status);
    const data = await api(`/api/employers/${encodeURIComponent(state.employerKey)}/shuttle-requests?${params}`);
    document.getElementById("view-root").innerHTML = `
        <div class="toolbar">
            <div class="toolbar-group">
                <select id="shuttle-filter" aria-label="Servis talebi durumu">
                    <option value="">Tüm durumlar</option>
                    ${["requested", "confirmed", "rejected", "cancelled", "replaced"].map((value) => `
                        <option value="${value}" ${status === value ? "selected" : ""}>${statusLabel(value)}</option>
                    `).join("")}
                </select>
            </div>
            <span class="employer-badge">${data.pagination.total} talep</span>
        </div>
        <section class="panel">
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Çalışan</th><th>Güzergah</th><th>Not</th><th>Durum</th><th>Tarih</th><th></th></tr></thead>
                    <tbody>
                    ${data.shuttleRequests.length ? data.shuttleRequests.map((item) => `
                        <tr>
                            <td><span class="cell-title">${escapeHtml(item.worker?.name || "İsim bekleniyor")}</span><span class="cell-subtitle">${escapeHtml(item.worker?.phone || shortId(item.userId))}</span></td>
                            <td><span class="cell-title">${escapeHtml(item.routeName || "-")}</span><span class="cell-subtitle">${escapeHtml(item.pickupWindow || "")}</span></td>
                            <td>${escapeHtml(item.pickupNote || "-")}</td>
                            <td>${statusBadge(item.status)}</td>
                            <td>${formatDate(item.createdAt)}</td>
                            <td>
                                ${["requested", "confirmed", "rejected"].includes(item.status)
                                    ? `<button class="button secondary small" type="button" data-shuttle-id="${escapeAttribute(item.id)}" data-status="${escapeAttribute(item.status)}">İncele</button>`
                                    : "-"}
                            </td>
                        </tr>
                    `).join("") : emptyTableRow(6, "Servis talebi bulunamadı.")}
                    </tbody>
                </table>
            </div>
        </section>
        ${paginationControls(data.pagination)}
    `;
    document.getElementById("shuttle-filter").addEventListener("change", (event) => {
        renderShuttleRequests(event.currentTarget.value);
    });
    document.querySelectorAll("[data-shuttle-id]").forEach((button) => {
        button.addEventListener("click", () => openShuttleDecision(button.dataset.shuttleId, button.dataset.status));
    });
    bindPagination((nextPage) => renderShuttleRequests(status, nextPage));
}

async function renderAuditEvents(
    outcome = state.auditOutcome,
    page = 1,
) {
    state.auditOutcome = outcome;
    state.auditPage = page;
    const params = new URLSearchParams({
        page: String(page),
        limit: "25",
    });
    if (outcome) params.set("outcome", outcome);
    const data = await api(
        `/api/employers/${encodeURIComponent(state.employerKey)}/audit-events?${params}`,
    );
    document.getElementById("view-root").innerHTML = `
        <div class="toolbar">
            <div class="toolbar-group">
                <select id="audit-filter" aria-label="Denetim sonucu">
                    <option value="" ${outcome === "" ? "selected" : ""}>Tüm sonuçlar</option>
                    <option value="success" ${outcome === "success" ? "selected" : ""}>Başarılı</option>
                    <option value="rejected" ${outcome === "rejected" ? "selected" : ""}>Reddedilen</option>
                </select>
            </div>
            <span class="employer-badge">${data.pagination.total} işlem</span>
        </div>
        <section class="panel">
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Tarih</th><th>Yönetici</th><th>İşlem</th><th>Hedef</th><th>Sonuç</th><th>İstek ID</th></tr></thead>
                    <tbody>
                        ${data.auditEvents.length
                            ? data.auditEvents.map(auditEventRow).join("")
                            : emptyTableRow(6, "Denetim kaydı bulunamadı.")}
                    </tbody>
                </table>
            </div>
        </section>
        ${paginationControls(data.pagination)}
    `;
    document.getElementById("audit-filter").addEventListener(
        "change",
        (event) => renderAuditEvents(event.currentTarget.value),
    );
    bindPagination((nextPage) => renderAuditEvents(outcome, nextPage));
}

function auditEventRow(event) {
    const outcomeLabel = event.outcome === "success"
        ? "Başarılı"
        : "Reddedildi";
    return `
        <tr>
            <td>${formatDate(event.createdAt)}</td>
            <td><span class="cell-title">${escapeHtml(event.username || "-")}</span><span class="cell-subtitle">${escapeHtml(event.authSource || "-")}</span></td>
            <td><span class="cell-title">${escapeHtml(auditActionLabel(event.action))}</span><span class="cell-subtitle">${escapeHtml(event.method || "-")} · HTTP ${escapeHtml(String(event.statusCode ?? "-"))}</span></td>
            <td>${escapeHtml(auditTargetLabel(event.target))}</td>
            <td><span class="status-badge ${event.outcome === "success" ? "completed" : "rejected"}">${outcomeLabel}</span></td>
            <td><span class="cell-subtitle">${escapeHtml(event.requestId || "-")}</span></td>
        </tr>`;
}

function auditActionLabel(action) {
    return {
        "admin.create_worker_invitation": "Çalışan daveti oluşturma",
        "admin.cancel_worker_invitation": "Çalışan daveti iptali",
        "admin.update_employer_worker_support_assignments": "Çalışan içeriği atama",
        "admin.retry_video_processing_job": "Video işlemeyi yeniden kuyruğa alma",
        "admin.correct_invalid_phone_worker": "Eski çalışan telefonunu düzeltme",
        "admin.cleanup_invalid_phone_worker": "Geçersiz çalışan kaydını temizleme",
        "auth.logout": "Oturum kapatma",
        "job_applications.update_employer_job_application": "Başvuru kararı güncelleme",
        "job_postings.create_job_posting": "İş ilanı oluşturma",
        "job_postings.update_job_posting": "İş ilanı güncelleme",
        "job_postings.delete_job_posting": "İş ilanı silme",
        "worker_support.answer_employer_question": "Çalışan sorusu yanıtlama",
        "worker_support.update_employer_shuttle_request": "Servis talebi güncelleme",
        "worker_support.update_employer_worker_config": "Çalışan içeriği güncelleme",
        "worker_support.create_employer_worker_config_item": "İçerik oluşturma",
        "worker_support.update_employer_worker_config_item": "İçerik güncelleme",
        "worker_support.delete_employer_worker_config_item": "İçerik silme",
        "worker_support.update_employer_shuttle_settings": "Servis ayarlarını güncelleme",
        "worker_support.create_employer_shuttle_route": "Servis rotası oluşturma",
        "worker_support.update_employer_shuttle_route": "Servis rotası güncelleme",
        "worker_support.delete_employer_shuttle_route": "Servis rotası silme",
    }[action] || action || "Bilinmeyen işlem";
}

function auditTargetLabel(target) {
    const entries = Object.entries(target || {})
        .filter(([key]) => key !== "employer_key");
    if (!entries.length) return "Genel";
    return entries
        .map(([key, value]) => `${key.replaceAll("_", " ")}: ${shortId(String(value))}`)
        .join(", ");
}

async function renderContent() {
    const response = await api(`/api/employers/${encodeURIComponent(state.employerKey)}/worker-config`);
    state.config = response.workerConfig;
    const meta = contentMeta[state.contentResource];
    const items = getContentItems(state.contentResource);
    document.getElementById("view-root").innerHTML = `
        <div class="content-layout">
            <section class="panel">
                <header class="panel-header"><div><h2>Servis ayarları</h2><p>Çalışanların servis talebi oluşturabilmesini yönetin</p></div></header>
                ${shuttleSettingsForm(state.config.shuttle || {})}
            </section>
            <div class="toolbar">
                <div class="segmented-control" role="tablist">
                    ${Object.entries(contentMeta).map(([key, value]) => `
                        <button class="segment ${key === state.contentResource ? "active" : ""}" type="button" data-content-tab="${key}">${escapeHtml(value.label)}</button>
                    `).join("")}
                </div>
                <button id="add-content-button" class="button primary" type="button">${escapeHtml(meta.singular)} ekle</button>
            </div>
            <section class="panel">
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>Başlık</th><th>Detay</th><th>Durum</th><th></th></tr></thead>
                        <tbody>
                            ${items.length ? items.map((item) => contentRow(state.contentResource, item)).join("") : emptyTableRow(4, `${meta.label} için kayıt bulunamadı.`)}
                        </tbody>
                    </table>
                </div>
            </section>
        </div>
    `;
    document.getElementById("shuttle-settings-form").addEventListener("submit", saveShuttleSettings);
    document.querySelectorAll("[data-content-tab]").forEach((button) => {
        button.addEventListener("click", () => {
            state.contentResource = button.dataset.contentTab;
            renderContent();
        });
    });
    document.getElementById("add-content-button").addEventListener("click", () => openContentDialog(null));
    document.querySelectorAll("[data-edit-content]").forEach((button) => {
        button.addEventListener("click", () => {
            const item = items.find((candidate) => candidate.id === button.dataset.editContent);
            openContentDialog(item);
        });
    });
    document.querySelectorAll("[data-delete-content]").forEach((button) => {
        button.addEventListener("click", () => deleteContentItem(button.dataset.deleteContent));
    });
}

function openContentDialog(item) {
    state.editingItem = item || null;
    const meta = contentMeta[state.contentResource];
    document.getElementById("item-dialog-title").textContent = item ? `${meta.singular} düzenle` : `${meta.singular} ekle`;
    document.getElementById("item-form-error").textContent = "";
    document.getElementById("item-form-fields").innerHTML = contentForm(state.contentResource, item || {});
    bindEditorControls();
    document.getElementById("item-dialog").showModal();
}

async function saveContentItem(event) {
    event.preventDefault();
    const errorElement = document.getElementById("item-form-error");
    const submitButton = event.currentTarget.querySelector("button[type=submit]");
    errorElement.textContent = "";
    submitButton.disabled = true;

    try {
        const payload = readContentPayload(state.contentResource);
        const basePath = `/api/employers/${encodeURIComponent(state.employerKey)}/worker-config/${contentMeta[state.contentResource].path}`;
        const path = state.editingItem ? `${basePath}/${encodeURIComponent(state.editingItem.id)}` : basePath;
        await api(path, {
            method: state.editingItem ? "PATCH" : "POST",
            body: payload,
        });
        document.getElementById("item-dialog").close();
        showToast("İçerik kaydedildi.");
        await renderContent();
    } catch (error) {
        errorElement.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

async function deleteContentItem(itemId) {
    const meta = contentMeta[state.contentResource];
    if (!window.confirm(`${meta.singular} kaydı silinsin mi?`)) return;
    try {
        await api(`/api/employers/${encodeURIComponent(state.employerKey)}/worker-config/${meta.path}/${encodeURIComponent(itemId)}`, {
            method: "DELETE",
        });
        showToast("İçerik silindi.");
        await renderContent();
    } catch (error) {
        setError(error.message);
    }
}

async function saveShuttleSettings(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const submitButton = form.querySelector("button[type=submit]");
    submitButton.disabled = true;
    try {
        await api(`/api/employers/${encodeURIComponent(state.employerKey)}/worker-config/shuttle`, {
            method: "PATCH",
            body: {
                enabled: form.elements.enabled.checked,
                title: form.elements.title.value.trim(),
                description: form.elements.description.value.trim(),
            },
        });
        showToast("Servis ayarları güncellendi.");
        await renderContent();
    } catch (error) {
        showToast(error.message);
    } finally {
        submitButton.disabled = false;
    }
}

function openApplicationDecision(application) {
    if (!application) return;
    state.decision = {
        type: "application",
        id: application.id,
        application,
    };
    document.getElementById("decision-title").textContent = "Başvuru durumunu güncelle";
    document.getElementById("decision-status").innerHTML = statusOptions(application.status, false);
    document.getElementById("decision-note").value = "";
    document.getElementById("decision-error").textContent = "";
    document.getElementById("interview-scheduled-at").value =
        toDateTimeLocal(application.interview?.scheduledAt);
    document.getElementById("interview-type").value =
        application.interview?.type || "onsite";
    document.getElementById("interview-location").value =
        application.interview?.location || "";
    document.getElementById("interview-note").value =
        application.interview?.note || "";
    const interviewResponse =
        application.interview?.response;
    const responseSummary = document.getElementById(
        "interview-response-summary",
    );
    responseSummary.hidden = !interviewResponse;
    document.getElementById(
        "interview-response-status",
    ).textContent = interviewResponse?.status === "confirmed"
        ? "Çalışan görüşmeye katılacak"
        : "Çalışan görüşmeye katılamayacak";
    const responseNote = document.getElementById(
        "interview-response-note",
    );
    responseNote.textContent = interviewResponse?.note || "";
    responseNote.hidden = !interviewResponse?.note;
    document.getElementById("interview-clear").checked = false;
    document.getElementById("interview-clear-label").hidden =
        !application.interview;
    syncDecisionInterviewFields();
    document.getElementById("decision-dialog").showModal();
}

function openShuttleDecision(requestId, status) {
    state.decision = {type: "shuttle", id: requestId};
    document.getElementById("decision-title").textContent = "Servis talebini sonuçlandır";
    document.getElementById("decision-status").innerHTML = ["confirmed", "rejected"].map((value) => `
        <option value="${value}" ${status === value ? "selected" : ""}>${statusLabel(value)}</option>
    `).join("");
    document.getElementById("decision-note").value = "";
    document.getElementById("decision-error").textContent = "";
    document.getElementById("application-interview-fields").hidden = true;
    document.getElementById("decision-dialog").showModal();
}

function syncDecisionInterviewFields() {
    const section = document.getElementById("application-interview-fields");
    const isApplication = state.decision?.type === "application";
    const activeStatus = ["reviewing", "shortlisted"].includes(
        document.getElementById("decision-status").value,
    );
    section.hidden = !isApplication || !activeStatus;
    const disabled = document.getElementById("interview-clear").checked;
    [
        "interview-scheduled-at",
        "interview-type",
        "interview-location",
        "interview-note",
    ].forEach((id) => {
        document.getElementById(id).disabled = disabled;
    });
}

async function saveDecision(event) {
    event.preventDefault();
    const errorElement = document.getElementById("decision-error");
    const submitButton = event.currentTarget.querySelector("button[type=submit]");
    const status = document.getElementById("decision-status").value;
    const note = document.getElementById("decision-note").value.trim();
    submitButton.disabled = true;
    errorElement.textContent = "";

    try {
        if (state.decision.type === "application") {
            const body = {status, note};
            const interview = readInterviewDecision();
            if (interview !== undefined) body.interview = interview;
            await api(`/api/employers/${encodeURIComponent(state.employerKey)}/job-applications/${encodeURIComponent(state.decision.id)}`, {
                method: "PATCH",
                body,
            });
        } else {
            await api(`/api/employers/${encodeURIComponent(state.employerKey)}/shuttle-requests/${encodeURIComponent(state.decision.id)}`, {
                method: "PATCH",
                body: {status, decisionNote: note},
            });
        }
        document.getElementById("decision-dialog").close();
        showToast("Durum güncellendi.");
        await loadCurrentView();
    } catch (error) {
        errorElement.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

function readInterviewDecision() {
    if (!["reviewing", "shortlisted"].includes(
        document.getElementById("decision-status").value,
    )) {
        return undefined;
    }
    if (document.getElementById("interview-clear").checked) {
        return null;
    }
    const scheduledAt = document.getElementById(
        "interview-scheduled-at",
    ).value;
    if (!scheduledAt) return undefined;
    const type = document.getElementById("interview-type").value;
    const location = document.getElementById(
        "interview-location",
    ).value.trim();
    if (type === "onsite" && !location) {
        throw new Error(
            "Yüz yüze görüşme için konum zorunludur.",
        );
    }
    return {
        scheduledAt: new Date(scheduledAt).toISOString(),
        type,
        location,
        note: document.getElementById("interview-note").value.trim(),
    };
}

function contentForm(resource, item) {
    const idField = `
        <label>Kimlik
            <input name="id" value="${escapeAttribute(item.id || "")}" ${item.id ? "disabled" : ""} placeholder="Otomatik oluşturulur">
        </label>`;
    if (resource === "assessments") {
        return `
            <div class="field-grid">
                ${idField}
                ${statusField(item.status)}
                <label>Başlık<input name="title" value="${escapeAttribute(item.title || "")}" maxlength="160" required></label>
                <label>Süre (dakika)<input name="durationMinutes" type="number" min="1" max="480" value="${item.durationMinutes || 10}" required></label>
                <label>Geçme puanı<input name="passScore" type="number" min="0" max="100" value="${item.passScore ?? 70}" required></label>
                <label class="check-label"><input name="required" type="checkbox" ${item.required ? "checked" : ""}> Zorunlu</label>
            </div>
            <label>Açıklama<textarea name="description" maxlength="1000">${escapeHtml(item.description || "")}</textarea></label>
            <section class="editor-section">
                <div class="editor-section-header"><h3>Sorular</h3><button class="button secondary small" type="button" data-add-question>Soru ekle</button></div>
                <div id="question-editors">${(item.questions?.length ? item.questions : [{}]).map(questionEditor).join("")}</div>
            </section>`;
    }
    if (resource === "trainings") {
        return `
            <div class="field-grid">
                ${idField}
                ${statusField(item.status)}
                <label>Başlık<input name="title" value="${escapeAttribute(item.title || "")}" maxlength="160" required></label>
                <label>Süre (dakika)<input name="durationMinutes" type="number" min="1" max="1440" value="${item.durationMinutes || 15}" required></label>
            </div>
            <label>Açıklama<textarea name="description" maxlength="1000">${escapeHtml(item.description || "")}</textarea></label>
            <section class="editor-section">
                <div class="editor-section-header"><h3>Modüller</h3><button class="button secondary small" type="button" data-add-module>Modül ekle</button></div>
                <div id="module-editors">${(item.modules?.length ? item.modules : [{}]).map(moduleEditor).join("")}</div>
            </section>`;
    }
    if (resource === "useful-info") {
        return `
            <div class="field-grid">
                ${idField}
                <label>Kategori<input name="category" value="${escapeAttribute(item.category || "general")}" maxlength="80" required></label>
            </div>
            <label>Başlık<input name="title" value="${escapeAttribute(item.title || "")}" maxlength="160" required></label>
            <label>İçerik<textarea name="body" rows="8" maxlength="10000" required>${escapeHtml(item.body || "")}</textarea></label>`;
    }
    if (resource === "qa-knowledge") {
        return `
            ${idField}
            <label>Anahtar kelimeler<input name="keywords" value="${escapeAttribute((item.keywords || []).join(", "))}" required><span class="helper-text">Virgülle ayırın.</span></label>
            <label>Cevap<textarea name="answer" rows="7" maxlength="4000" required>${escapeHtml(item.answer || "")}</textarea></label>`;
    }
    return `
        ${idField}
        <label>Rota adı<input name="name" value="${escapeAttribute(item.name || "")}" maxlength="160" required></label>
        <label>Alım aralığı<input name="pickupWindow" value="${escapeAttribute(item.pickupWindow || "")}" maxlength="120" placeholder="07:00 - 07:30" required></label>`;
}

function bindEditorControls() {
    const addQuestion = document.querySelector("[data-add-question]");
    if (addQuestion) {
        addQuestion.addEventListener("click", () => {
            document.getElementById("question-editors").insertAdjacentHTML("beforeend", questionEditor({}));
            bindRemoveButtons();
        });
    }
    const addModule = document.querySelector("[data-add-module]");
    if (addModule) {
        addModule.addEventListener("click", () => {
            document.getElementById("module-editors").insertAdjacentHTML("beforeend", moduleEditor({}));
            bindRemoveButtons();
        });
    }
    bindRemoveButtons();
}

function bindRemoveButtons() {
    document.querySelectorAll(".remove-editor-row").forEach((button) => {
        button.onclick = () => {
            const container = button.closest(".editor-row").parentElement;
            if (container.querySelectorAll(".editor-row").length > 1) {
                button.closest(".editor-row").remove();
            }
        };
    });
}

function readContentPayload(resource) {
    const form = document.getElementById("item-form");
    const formData = new FormData(form);
    const payload = {};
    const id = formData.get("id")?.trim();
    if (id) payload.id = id;

    if (resource === "assessments") {
        return {
            ...payload,
            title: formData.get("title").trim(),
            description: formData.get("description").trim(),
            status: formData.get("status"),
            durationMinutes: Number(formData.get("durationMinutes")),
            required: form.elements.required.checked,
            passScore: Number(formData.get("passScore")),
            questions: [...document.querySelectorAll(".question-editor")].map((row, index) => {
                const questionId = row.querySelector("[data-question-id]").value.trim() || `question-${index + 1}`;
                const correctId = row.querySelector("[data-correct-id]").value.trim() || `${questionId}-correct`;
                const wrongId = row.querySelector("[data-wrong-id]").value.trim() || `${questionId}-wrong`;
                return {
                    id: questionId,
                    prompt: row.querySelector("[data-question-prompt]").value.trim(),
                    options: [
                        {id: correctId, label: row.querySelector("[data-correct-label]").value.trim(), score: 100},
                        {id: wrongId, label: row.querySelector("[data-wrong-label]").value.trim(), score: 0},
                    ],
                };
            }),
        };
    }
    if (resource === "trainings") {
        return {
            ...payload,
            title: formData.get("title").trim(),
            description: formData.get("description").trim(),
            status: formData.get("status"),
            durationMinutes: Number(formData.get("durationMinutes")),
            modules: [...document.querySelectorAll(".module-editor")].map((row, index) => ({
                id: row.querySelector("[data-module-id]").value.trim() || `module-${index + 1}`,
                title: row.querySelector("[data-module-title]").value.trim(),
                body: row.querySelector("[data-module-body]").value.trim(),
            })),
        };
    }
    if (resource === "useful-info") {
        return {
            ...payload,
            title: formData.get("title").trim(),
            body: formData.get("body").trim(),
            category: formData.get("category").trim(),
        };
    }
    if (resource === "qa-knowledge") {
        return {
            ...payload,
            keywords: formData.get("keywords").split(",").map((value) => value.trim()).filter(Boolean),
            answer: formData.get("answer").trim(),
        };
    }
    return {
        ...payload,
        name: formData.get("name").trim(),
        pickupWindow: formData.get("pickupWindow").trim(),
    };
}

function questionEditor(question = {}) {
    const options = question.options || [];
    const correct = options.reduce((best, option) => (Number(option.score) > Number(best?.score ?? -1) ? option : best), null) || {};
    const wrong = options.find((option) => option !== correct) || {};
    return `
        <div class="editor-row question-editor">
            <button class="remove-editor-row" type="button">Soruyu kaldır</button>
            <div class="field-grid">
                <label>Soru kimliği<input data-question-id value="${escapeAttribute(question.id || "")}" placeholder="Otomatik"></label>
                <label>Soru<input data-question-prompt value="${escapeAttribute(question.prompt || "")}" maxlength="500" required></label>
                <label>Doğru seçenek<input data-correct-label value="${escapeAttribute(correct.label || "")}" maxlength="300" required></label>
                <label>Doğru seçenek kimliği<input data-correct-id value="${escapeAttribute(correct.id || "")}" placeholder="Otomatik"></label>
                <label>Yanlış seçenek<input data-wrong-label value="${escapeAttribute(wrong.label || "")}" maxlength="300" required></label>
                <label>Yanlış seçenek kimliği<input data-wrong-id value="${escapeAttribute(wrong.id || "")}" placeholder="Otomatik"></label>
            </div>
        </div>`;
}

function moduleEditor(module = {}) {
    return `
        <div class="editor-row module-editor">
            <button class="remove-editor-row" type="button">Modülü kaldır</button>
            <div class="field-grid">
                <label>Modül kimliği<input data-module-id value="${escapeAttribute(module.id || "")}" placeholder="Otomatik"></label>
                <label>Başlık<input data-module-title value="${escapeAttribute(module.title || "")}" maxlength="160" required></label>
            </div>
            <label>İçerik<textarea data-module-body maxlength="10000" required>${escapeHtml(module.body || "")}</textarea></label>
        </div>`;
}

function statusField(status = "available") {
    return `
        <label>Durum
            <select name="status">
                ${["available", "draft", "archived"].map((value) => `<option value="${value}" ${status === value ? "selected" : ""}>${statusLabel(value)}</option>`).join("")}
            </select>
        </label>`;
}

function shuttleSettingsForm(shuttle) {
    return `
        <form id="shuttle-settings-form" class="settings-form">
            <label class="check-label"><input name="enabled" type="checkbox" ${shuttle.enabled ? "checked" : ""}> Servis açık</label>
            <label>Başlık<input name="title" value="${escapeAttribute(shuttle.title || "Servis Planlama")}" maxlength="160" required></label>
            <label>Açıklama<input name="description" value="${escapeAttribute(shuttle.description || "")}" maxlength="1000"></label>
            <button class="button primary" type="submit">Ayarları kaydet</button>
        </form>`;
}

function getContentItems(resource) {
    if (resource === "shuttle-routes") return state.config.shuttle?.routes || [];
    return state.config[contentMeta[resource].key] || [];
}

function contentRow(resource, item) {
    let title = item.title || item.answer || item.name || "-";
    let detail = item.description || item.body || item.pickupWindow || (item.keywords || []).join(", ");
    let status = item.status || (resource === "assessments" && item.required ? "Zorunlu" : "Aktif");
    return `
        <tr>
            <td><span class="cell-title">${escapeHtml(title)}</span><span class="cell-subtitle">${escapeHtml(item.id || "")}</span></td>
            <td><span class="cell-title">${escapeHtml(detail || "-")}</span></td>
            <td>${item.status ? statusBadge(item.status) : escapeHtml(status)}</td>
            <td><div class="actions">
                <button class="button secondary small" type="button" data-edit-content="${escapeAttribute(item.id)}">Düzenle</button>
                <button class="button danger small" type="button" data-delete-content="${escapeAttribute(item.id)}">Sil</button>
            </div></td>
        </tr>`;
}

function applicationTable(items, actionable) {
    return `
        <div class="table-wrap">
            <table>
                <thead><tr><th>Aday</th><th>Pozisyon</th><th>Eşleşme</th><th>Durum</th><th>Tarih</th>${actionable ? "<th></th>" : ""}</tr></thead>
                <tbody>
                    ${items.length ? items.map((item) => `
                        <tr>
                            <td>
                                ${item.userId ? `
                                    <button class="cell-link" type="button" data-worker-id="${escapeAttribute(item.userId)}">${escapeHtml(item.candidate?.name || "İsim bekleniyor")}</button>
                                ` : `<span class="cell-title">${escapeHtml(item.candidate?.name || "İsim bekleniyor")}</span>`}
                                <span class="cell-subtitle">${escapeHtml(item.candidate?.phone || "")}</span>
                            </td>
                            <td><span class="cell-title">${escapeHtml(item.job?.title || "-")}</span><span class="cell-subtitle">${escapeHtml(item.job?.location || "")}</span></td>
                            <td>%${item.job?.matchScore ?? "-"}</td>
                            <td>
                                ${statusBadge(item.status)}
                                ${item.interview?.scheduledAt ? `
                                    <span class="cell-subtitle">Görüşme: ${formatDate(item.interview.scheduledAt)}</span>
                                    ${item.interview.response ? `
                                        <span class="cell-subtitle">
                                            Yanıt: ${item.interview.response.status === "confirmed"
                                                ? "Katılacak"
                                                : "Katılamayacak"}
                                        </span>
                                    ` : ""}
                                ` : ""}
                            </td>
                            <td>${formatDate(item.createdAt)}</td>
                            ${actionable ? `<td>${["withdrawn", "hired"].includes(item.status)
                                ? "-"
                                : `<button class="button secondary small" type="button" data-application-id="${escapeAttribute(item.id)}" data-status="${escapeAttribute(item.status)}">Güncelle</button>`}</td>` : ""}
                        </tr>
                    `).join("") : emptyTableRow(actionable ? 6 : 5, "Başvuru bulunamadı.")}
                </tbody>
            </table>
        </div>`;
}

function workerRow(worker) {
    return `
        <tr>
            <td><span class="cell-title">${escapeHtml(worker.name || "İsim bekleniyor")}</span><span class="cell-subtitle">${escapeHtml(worker.phone)}</span></td>
            <td><div class="actions">${statusBadge(worker.profileStatus)}${profileReviewBadge(worker.profileReviewStatus)}</div></td>
            <td><span class="cell-title">${escapeHtml((worker.profile?.skills || []).join(", ") || "-")}</span></td>
            <td>${worker.applicationCount}</td>
            <td>${formatDate(worker.createdAt)}</td>
            <td><button class="button secondary small" type="button" data-worker-id="${escapeAttribute(worker.id)}">Detay</button></td>
        </tr>`;
}

function invitationRow(invitation) {
    return `
        <tr>
            <td><span class="cell-title">${escapeHtml(invitation.phone)}</span></td>
            <td>${escapeHtml(invitation.createdBy || "-")}</td>
            <td>${formatDate(invitation.createdAt)}</td>
            <td>${formatDate(invitation.expiresAt)}</td>
            <td><button class="button danger small" type="button" data-cancel-invitation="${escapeAttribute(invitation.id)}">İptal et</button></td>
        </tr>`;
}

function jobPostingRow(posting) {
    const statusAction = posting.status === "published"
        ? `<button class="button secondary small" type="button" data-job-status="${escapeAttribute(posting.id)}" data-next-status="closed">Kapat</button>`
        : `<button class="button secondary small" type="button" data-job-status="${escapeAttribute(posting.id)}" data-next-status="published">Yayınla</button>`;
    return `
        <tr>
            <td><span class="cell-title">${escapeHtml(posting.title)}</span><span class="cell-subtitle">${escapeHtml(posting.company)} · ${escapeHtml(posting.location)}</span></td>
            <td><span class="cell-title">${escapeHtml(employmentTypeLabel(posting.employmentType))}</span><span class="cell-subtitle">${escapeHtml(shiftLabel(posting.shift))}</span></td>
            <td><span class="cell-title">${escapeHtml((posting.requiredSkills || []).join(", "))}</span><span class="cell-subtitle">${escapeHtml((posting.optionalSkills || []).join(", "))}</span></td>
            <td>${posting.openings}</td>
            <td>${posting.applicationCount || 0}</td>
            <td>${statusBadge(posting.status)}</td>
            <td><div class="actions">
                <button class="button secondary small" type="button" data-edit-job="${escapeAttribute(posting.id)}">Düzenle</button>
                ${statusAction}
                <button class="button danger small" type="button" data-delete-job="${escapeAttribute(posting.id)}">Sil</button>
            </div></td>
        </tr>`;
}

function commaSeparatedValues(value) {
    return [...new Set(
        value.split(",").map((item) => item.trim()).filter(Boolean),
    )];
}

function employmentTypeLabel(value) {
    return {
        full_time: "Tam zamanlı",
        part_time: "Yarı zamanlı",
        temporary: "Dönemsel",
        contract: "Sözleşmeli",
    }[value] || value || "-";
}

function shiftLabel(value) {
    return {
        day: "Gündüz vardiyası",
        night: "Gece vardiyası",
        rotating: "Dönüşümlü vardiya",
        flexible: "Esnek vardiya",
    }[value] || value || "-";
}

function statusOptions(selected, includeAll) {
    const statuses = [
        "submitted",
        "reviewing",
        "shortlisted",
        "rejected",
        "hired",
        ...(includeAll ? ["withdrawn"] : []),
    ];
    return `${includeAll ? '<option value="">Tüm durumlar</option>' : ""}${statuses.map((value) => `
        <option value="${value}" ${selected === value ? "selected" : ""}>${statusLabel(value)}</option>
    `).join("")}`;
}

function statusBadge(status) {
    return `<span class="status-badge ${escapeAttribute(status || "")}">${escapeHtml(statusLabel(status))}</span>`;
}

function profileReviewBadge(status) {
    const labels = {
        pending_video: "Video bekleniyor",
        pending: "Ad onayı bekliyor",
        confirmed: "Ad doğrulandı",
    };
    const normalized = status || "pending_video";
    return `<span class="status-badge ${escapeAttribute(normalized)}">${escapeHtml(labels[normalized] || "Ad onayı bekliyor")}</span>`;
}

function consentBadge(consent) {
    const status = consent?.status || "required";
    const labels = {
        accepted: "Onay verildi",
        revoked: "Onay geri çekildi",
        required: "Onay bekleniyor",
    };
    const date = consent?.acceptedAt
        ? ` · ${formatDate(consent.acceptedAt)}`
        : "";
    return `<span class="status-badge ${escapeAttribute(status)}">${escapeHtml((labels[status] || "Onay bekleniyor") + date)}</span>`;
}

function statusLabel(status) {
    if (!status) return "-";
    return statusLabels[status] || status.replaceAll("_", " ");
}

function contentCountRow(label, value) {
    return `<tr><td>${escapeHtml(label)}</td><td><strong>${value}</strong></td></tr>`;
}

function emptyTableRow(columns, message) {
    return `<tr><td colspan="${columns}" class="empty-state">${escapeHtml(message)}</td></tr>`;
}

function paginationControls(pagination) {
    if (!pagination || pagination.pages <= 1) return "";
    return `
        <nav class="pagination" aria-label="Sayfalama">
            <button class="button secondary small" type="button" data-page="${pagination.page - 1}" ${pagination.page <= 1 ? "disabled" : ""}>Önceki</button>
            <span>${pagination.page} / ${pagination.pages}</span>
            <button class="button secondary small" type="button" data-page="${pagination.page + 1}" ${pagination.page >= pagination.pages ? "disabled" : ""}>Sonraki</button>
        </nav>`;
}

function bindPagination(onPage) {
    document.querySelectorAll("[data-page]").forEach((button) => {
        button.addEventListener("click", () => onPage(Number(button.dataset.page)));
    });
}

function shortId(value) {
    if (!value) return "-";
    return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return new Intl.DateTimeFormat("tr-TR", {dateStyle: "short", timeStyle: "short"}).format(date);
}

function toDateTimeLocal(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const local = new Date(
        date.getTime() - date.getTimezoneOffset() * 60_000,
    );
    return local.toISOString().slice(0, 16);
}

function setLoading(loading) {
    document.getElementById("loading-state").hidden = !loading;
    document.getElementById("view-root").hidden = loading;
}

function setError(message) {
    const element = document.getElementById("error-state");
    element.textContent = message;
    element.hidden = !message;
    if (message) document.getElementById("view-root").innerHTML = "";
}

function showToast(message) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.classList.add("visible");
    window.setTimeout(() => toast.classList.remove("visible"), 2600);
}

async function api(path, options = {}) {
    const headers = {"Accept": "application/json"};
    const method = (options.method || "GET").toUpperCase();
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (
        options.auth !== false
        && state.csrfToken
        && !["GET", "HEAD", "OPTIONS"].includes(method)
    ) {
        headers["X-CSRF-Token"] = state.csrfToken;
    }

    const response = await fetch(path, {
        method,
        headers,
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
        credentials: "same-origin",
    });
    if (response.status === 204) return null;

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        if (response.status === 401 && options.auth !== false) {
            clearSession();
            showLogin("Oturum süreniz doldu. Yeniden giriş yapın.");
        }
        throw new Error(payload.message || "İşlem tamamlanamadı.");
    }
    return payload;
}

function readCookie(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    const item = document.cookie
        .split(";")
        .map((value) => value.trim())
        .find((value) => value.startsWith(prefix));
    return item ? decodeURIComponent(item.slice(prefix.length)) : null;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
    return escapeHtml(value);
}
