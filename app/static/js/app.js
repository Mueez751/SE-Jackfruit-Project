// State
let currentRole = "admin";
let currentToken = null;
let currentTab = "dashboard";
let cachedDonors = [];
let cachedUnits = [];
let cachedRequests = [];

// Initialize
document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  setupRoleSwitcher();
  await switchRole("admin");
  loadNotifications();
  // Auto-refresh notifications every 30s
  setInterval(loadNotifications, 30000);
});

// Toast notification
function showToast(message, type = "success") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 4000);
}

// API Helper
async function apiCall(endpoint, method = "GET", body = null) {
  const headers = { "Content-Type": "application/json" };
  if (currentToken) {
    headers["Authorization"] = `Bearer ${currentToken}`;
  }
  const opts = { method, headers };
  if (body) {
    opts.body = JSON.stringify(body);
  }

  try {
    const res = await fetch(endpoint, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "API request failed");
    }
    return await res.json();
  } catch (error) {
    showToast(error.message, "error");
    throw error;
  }
}

// Role Switcher
function setupRoleSwitcher() {
  document.querySelectorAll(".role-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const role = btn.dataset.role;
      switchRole(role);
    });
  });
}

async function switchRole(role) {
  try {
    const res = await apiCall(`/api/demo/switch-role?role=${role}`, "POST");
    if (res.session) {
      currentRole = role;
      currentToken = res.session.token;

      document.querySelectorAll(".role-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.role === role);
      });

      document.getElementById("currentUserDisplay").innerText = `${res.session.full_name} (${role.toUpperCase()})`;
      showToast(`Switched active session to: ${role.toUpperCase()}`, "success");

      // Update role-specific visibility
      updateRoleAccess(role);
      loadTabContent(currentTab);
    }
  } catch (err) {
    console.error("Role switch error:", err);
  }
}

function updateRoleAccess(role) {
  const adminTab = document.querySelector('[data-tab="admin"]');
  if (adminTab) {
    adminTab.style.display = (role === "admin") ? "flex" : "none";
  }
}

// Tabs
function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabName = btn.dataset.tab;
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

      btn.classList.add("active");
      const target = document.getElementById(`tab-${tabName}`);
      if (target) {
        target.classList.add("active");
        currentTab = tabName;
        loadTabContent(tabName);
      }
    });
  });
}

function loadTabContent(tabName) {
  switch (tabName) {
    case "dashboard":
      loadDashboard();
      break;
    case "inventory":
      loadInventory();
      break;
    case "donors":
      loadDonors();
      break;
    case "collections":
      loadCollectionsView();
      break;
    case "requests":
      loadRequests();
      break;
    case "issues":
      loadIssues();
      break;
    case "reports":
      loadReportsView();
      break;
    case "admin":
      if (currentRole === "admin") {
        loadAdminUsers();
        loadAuditLogs();
      }
      break;
  }
}

// ===================== DASHBOARD =====================
async function loadDashboard() {
  try {
    const data = await apiCall("/api/inventory/summary");
    document.getElementById("kpiTotalUnits").innerText = data.total_units;
    document.getElementById("kpiAvailableUnits").innerText = data.available_units;
    document.getElementById("kpiQuarantinedUnits").innerText = data.quarantined_units;
    document.getElementById("kpiExpiredUnits").innerText = data.expired_units;
    document.getElementById("kpiIssuedUnits").innerText = data.issued_units;

    // Stock Matrix
    const matrixContainer = document.getElementById("dashboardStockMatrix");
    matrixContainer.innerHTML = "";
    const bloodGroups = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];

    bloodGroups.forEach((bg) => {
      const count = data.group_totals[bg] || 0;
      const isLow = count < 5;
      const card = document.createElement("div");
      card.className = "matrix-item";
      card.innerHTML = `
        <div class="matrix-group">${bg}</div>
        <div class="matrix-count">${count} Units</div>
        <span class="badge ${isLow ? 'badge-danger' : 'badge-success'}">${isLow ? 'Low Stock' : 'Adequate'}</span>
      `;
      matrixContainer.appendChild(card);
    });

    // Recent requests
    const reqs = await apiCall("/api/requests");
    const reqList = document.getElementById("dashboardRecentRequests");
    reqList.innerHTML = "";
    reqs.slice(0, 5).forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${r.request_id}</strong></td>
        <td>${r.hospital_name}</td>
        <td><span class="badge badge-info">${r.patient_blood_group}</span></td>
        <td>${r.component_type}</td>
        <td><span class="badge ${r.urgency === 'Emergency' ? 'badge-danger' : r.urgency === 'Urgent' ? 'badge-warning' : 'badge-neutral'}">${r.urgency}</span></td>
        <td><span class="badge ${r.status === 'Approved' ? 'badge-success' : r.status === 'Pending' ? 'badge-warning' : 'badge-neutral'}">${r.status}</span></td>
      `;
      reqList.appendChild(tr);
    });
  } catch (err) {
    console.error("Dashboard load failed:", err);
  }
}

// ===================== INVENTORY =====================
async function loadInventory() {
  const bg = document.getElementById("invFilterGroup").value;
  const comp = document.getElementById("invFilterComp").value;
  const st = document.getElementById("invFilterStatus").value;
  const q = document.getElementById("invSearch").value;

  let url = "/api/inventory/units?";
  if (bg) url += `blood_group=${encodeURIComponent(bg)}&`;
  if (comp) url += `component_type=${encodeURIComponent(comp)}&`;
  if (st) url += `status=${encodeURIComponent(st)}&`;
  if (q) url += `search=${encodeURIComponent(q)}&`;

  try {
    const units = await apiCall(url);
    cachedUnits = units;
    const tbody = document.getElementById("inventoryTableBody");
    tbody.innerHTML = "";

    if (units.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:#64748b; padding:2rem;">No blood units match filters.</td></tr>`;
      return;
    }

    units.forEach((u) => {
      let statusBadge = "badge-success";
      if (u.status === "Quarantined") statusBadge = "badge-purple";
      else if (u.status === "Reserved") statusBadge = "badge-warning";
      else if (u.status === "Expired") statusBadge = "badge-danger";
      else if (u.status === "Discarded") statusBadge = "badge-danger";
      else if (u.status === "Issued") statusBadge = "badge-neutral";

      let shelfLifeBadge = "";
      if (u.is_expired) {
        shelfLifeBadge = `<span class="badge badge-danger">EXPIRED</span>`;
      } else if (u.days_until_expiry <= 3) {
        shelfLifeBadge = `<span class="badge badge-warning">${u.days_until_expiry}d left (CRITICAL)</span>`;
      } else {
        shelfLifeBadge = `<span class="badge badge-info">${u.days_until_expiry}d left</span>`;
      }

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${u.unit_id}</strong></td>
        <td><span class="badge badge-danger" style="font-weight:700;">${u.blood_group}</span></td>
        <td>${u.component_type}</td>
        <td>${u.volume_ml} mL</td>
        <td>${u.collection_date}</td>
        <td>${u.expiry_date} ${shelfLifeBadge}</td>
        <td><span class="badge ${statusBadge}">${u.status}</span></td>
        <td>${u.storage_location}</td>
        <td>
          ${u.status !== 'Issued' && u.status !== 'Discarded' ? `
            <button class="btn btn-sm btn-outline" onclick="openStatusModal('${u.unit_id}', '${u.status}')">Action</button>
          ` : '<span style="color:#94a3b8; font-size:0.75rem;">Terminal</span>'}
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Inventory error:", err);
  }
}

async function triggerExpiryCheck() {
  try {
    const res = await apiCall("/api/inventory/check-expiry", "POST");
    showToast(res.message, "success");
    loadInventory();
    loadNotifications();
  } catch (err) {}
}

function openStatusModal(unitId, currentStatus) {
  document.getElementById("statusModalUnitId").value = unitId;
  document.getElementById("statusModalDisplayUnit").innerText = unitId;
  document.getElementById("statusModalTarget").value = (currentStatus === "Quarantined") ? "Available" : "Quarantined";
  document.getElementById("statusModalReason").value = "";
  openModal("unitStatusModal");
}

async function submitUnitStatus() {
  const unitId = document.getElementById("statusModalUnitId").value;
  const status = document.getElementById("statusModalTarget").value;
  const reason = document.getElementById("statusModalReason").value.trim();

  if (!reason) {
    showToast("Reason is mandatory for status change.", "warning");
    return;
  }

  try {
    await apiCall(`/api/inventory/units/${unitId}/status`, "PATCH", { status, reason });
    showToast(`Unit ${unitId} status updated to ${status}.`, "success");
    closeModal("unitStatusModal");
    loadInventory();
  } catch (err) {}
}

// ===================== DONORS =====================
async function loadDonors() {
  const q = document.getElementById("donorSearch").value;
  const bg = document.getElementById("donorFilterGroup").value;

  let url = "/api/donors?";
  if (q) url += `search=${encodeURIComponent(q)}&`;
  if (bg) url += `blood_group=${encodeURIComponent(bg)}&`;

  try {
    const donors = await apiCall(url);
    cachedDonors = donors;
    const tbody = document.getElementById("donorsTableBody");
    tbody.innerHTML = "";

    if (donors.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:2rem; color:#64748b;">No donors found.</td></tr>`;
      return;
    }

    donors.forEach((d) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${d.donor_id}</strong></td>
        <td>${d.full_name}</td>
        <td>${d.age} / ${d.gender}</td>
        <td><span class="badge badge-danger">${d.blood_group}</span></td>
        <td>${d.phone}</td>
        <td><span class="badge badge-info">${d.donation_count} Donations</span></td>
        <td>${d.last_donation_date || 'Never'}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="openEligibilityModal('${d.donor_id}', '${d.full_name}')">Screen Vitals</button>
          <button class="btn btn-sm btn-outline" onclick="openHistoryModal('${d.donor_id}')">History</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {}
}

function openRegisterDonorModal() {
  document.getElementById("newDonorName").value = "";
  document.getElementById("newDonorAge").value = "";
  document.getElementById("newDonorGender").value = "Male";
  document.getElementById("newDonorGroup").value = "O+";
  document.getElementById("newDonorPhone").value = "";
  document.getElementById("newDonorEmail").value = "";
  document.getElementById("newDonorAddress").value = "";
  openModal("registerDonorModal");
}

async function submitNewDonor() {
  const full_name = document.getElementById("newDonorName").value.trim();
  const age = parseInt(document.getElementById("newDonorAge").value, 10);
  const gender = document.getElementById("newDonorGender").value;
  const blood_group = document.getElementById("newDonorGroup").value;
  const phone = document.getElementById("newDonorPhone").value.trim();
  const email = document.getElementById("newDonorEmail").value.trim() || null;
  const address = document.getElementById("newDonorAddress").value.trim() || null;

  if (!full_name || !age || !phone) {
    showToast("Name, age, and phone number are required.", "warning");
    return;
  }

  try {
    const res = await apiCall("/api/donors", "POST", {
      full_name, age, gender, blood_group, phone, email, address
    });
    showToast(`Donor registered! Assigned ID: ${res.donor_id}`, "success");
    closeModal("registerDonorModal");
    loadDonors();
  } catch (err) {}
}

function openEligibilityModal(donorId, donorName) {
  document.getElementById("eligModalDonorId").value = donorId;
  document.getElementById("eligModalDonorName").innerText = `${donorName} (${donorId})`;
  document.getElementById("eligWeight").value = "65.0";
  document.getElementById("eligHemoglobin").value = "14.0";
  document.getElementById("eligSystolic").value = "120";
  document.getElementById("eligDiastolic").value = "80";
  document.getElementById("eligPulse").value = "72";
  document.getElementById("eligDaysSince").value = "95";
  document.getElementById("eligRemarks").value = "";
  document.getElementById("eligResultBox").style.display = "none";
  openModal("eligibilityModal");
}

async function submitEligibilityCheck() {
  const donorId = document.getElementById("eligModalDonorId").value;
  const weight_kg = parseFloat(document.getElementById("eligWeight").value);
  const hemoglobin_g_dl = parseFloat(document.getElementById("eligHemoglobin").value);
  const systolic_bp = parseInt(document.getElementById("eligSystolic").value, 10);
  const diastolic_bp = parseInt(document.getElementById("eligDiastolic").value, 10);
  const pulse = parseInt(document.getElementById("eligPulse").value, 10);
  const days_since_last_donation = parseInt(document.getElementById("eligDaysSince").value, 10);
  const medical_flags = document.getElementById("eligRemarks").value.trim() || null;

  try {
    const res = await apiCall(`/api/donors/${donorId}/eligibility`, "POST", {
      weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse,
      days_since_last_donation, medical_flags
    });

    const box = document.getElementById("eligResultBox");
    box.style.display = "block";
    if (res.is_eligible) {
      box.className = "alert alert-success";
      box.style.background = "#dcfce7";
      box.style.color = "#16a34a";
      box.style.padding = "0.75rem";
      box.style.borderRadius = "6px";
      box.innerHTML = `<strong>ELIGIBLE:</strong> Donor meets all criteria (Age, Weight >= 50kg, Hb >= 12.5, Safe BP/Pulse, Donation Interval >= 90d).`;
      showToast("Eligibility Check: PASSED", "success");
    } else {
      box.className = "alert alert-danger";
      box.style.background = "#fee2e2";
      box.style.color = "#dc2626";
      box.style.padding = "0.75rem";
      box.style.borderRadius = "6px";
      box.innerHTML = `<strong>INELIGIBLE:</strong><br>${res.rejection_reasons.join("<br>")}`;
      showToast("Eligibility Check: REJECTED", "error");
    }
  } catch (err) {}
}

async function openHistoryModal(donorId) {
  try {
    const res = await apiCall(`/api/donors/${donorId}/history`);
    document.getElementById("historyModalDonorTitle").innerText = `Donation History: ${res.full_name} (${res.blood_group})`;
    const tbody = document.getElementById("donorHistoryTableBody");
    tbody.innerHTML = "";

    if (res.history.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:1.5rem; color:#64748b;">No donations on record.</td></tr>`;
    } else {
      res.history.forEach((h) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong>${h.collection_id}</strong></td>
          <td>${h.collection_date}</td>
          <td>${h.volume_ml} mL</td>
          <td>${h.unit_id || 'N/A'}</td>
          <td>${h.component_type || 'Whole Blood'}</td>
          <td><span class="badge badge-success">${h.status}</span></td>
        `;
        tbody.appendChild(tr);
      });
    }
    openModal("donorHistoryModal");
  } catch (err) {}
}

// ===================== COLLECTIONS =====================
async function loadCollectionsView() {
  try {
    const donors = await apiCall("/api/donors");
    const select = document.getElementById("collDonorSelect");
    select.innerHTML = '<option value="">-- Choose Registered Donor --</option>';
    donors.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.donor_id;
      opt.innerText = `${d.donor_id} - ${d.full_name} (${d.blood_group})`;
      opt.dataset.group = d.blood_group;
      select.appendChild(opt);
    });

    select.onchange = () => {
      const selected = select.options[select.selectedIndex];
      if (selected && selected.dataset.group) {
        document.getElementById("collBloodGroup").value = selected.dataset.group;
      }
    };
  } catch (err) {}
}

async function submitCollection() {
  const donor_id = document.getElementById("collDonorSelect").value;
  const blood_group = document.getElementById("collBloodGroup").value;
  const component_type = document.getElementById("collComponent").value;
  const volume_ml = parseFloat(document.getElementById("collVolume").value);

  if (!donor_id) {
    showToast("Please select a donor.", "warning");
    return;
  }

  try {
    const res = await apiCall("/api/collections", "POST", {
      donor_id, blood_group, component_type, volume_ml
    });
    showToast(`Collection accepted! Created unit ${res.data.unit_id} (Expires ${res.data.expiry_date})`, "success");
    document.getElementById("collResultBox").style.display = "block";
    document.getElementById("collResultDetails").innerHTML = `
      <strong>Unit ID:</strong> ${res.data.unit_id}<br>
      <strong>Component:</strong> ${res.data.blood_group} ${res.data.component_type}<br>
      <strong>Expiry Date:</strong> ${res.data.expiry_date}
    `;
  } catch (err) {
    // If donor was ineligible, backend will reject with details
  }
}

// ===================== REQUESTS =====================
async function loadRequests() {
  const st = document.getElementById("reqFilterStatus").value;
  const urg = document.getElementById("reqFilterUrgency").value;
  const q = document.getElementById("reqSearch").value;

  let url = "/api/requests?";
  if (st) url += `status=${encodeURIComponent(st)}&`;
  if (urg) url += `urgency=${encodeURIComponent(urg)}&`;
  if (q) url += `search=${encodeURIComponent(q)}&`;

  try {
    const reqs = await apiCall(url);
    cachedRequests = reqs;
    const tbody = document.getElementById("requestsTableBody");
    tbody.innerHTML = "";

    if (reqs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:2rem; color:#64748b;">No blood requests match criteria.</td></tr>`;
      return;
    }

    reqs.forEach((r) => {
      let urgBadge = "badge-neutral";
      if (r.urgency === "Emergency") urgBadge = "badge-danger";
      else if (r.urgency === "Urgent") urgBadge = "badge-warning";

      let statusBadge = "badge-neutral";
      if (r.status === "Approved") statusBadge = "badge-success";
      else if (r.status === "Pending") statusBadge = "badge-warning";
      else if (r.status === "Fulfilled") statusBadge = "badge-info";
      else if (r.status === "Rejected") statusBadge = "badge-danger";

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${r.request_id}</strong></td>
        <td>${r.hospital_name}<br><small style="color:#64748b;">Dr. ${r.requester_name}</small></td>
        <td>${r.patient_name}</td>
        <td><span class="badge badge-danger">${r.patient_blood_group}</span></td>
        <td>${r.component_type}</td>
        <td>${r.quantity} Unit(s)</td>
        <td><span class="badge ${urgBadge}">${r.urgency}</span></td>
        <td><span class="badge ${statusBadge}">${r.status}</span></td>
        <td>
          ${r.status === 'Pending' ? `
            <button class="btn btn-sm btn-primary" onclick="openDecisionModal('${r.request_id}')">Decide</button>
          ` : ''}
          ${r.status === 'Approved' ? `
            <button class="btn btn-sm btn-secondary" onclick="openFefoModal('${r.request_id}')">FEFO Allocate</button>
            ${r.allocated_units && r.allocated_units.length > 0 ? `
              <button class="btn btn-sm btn-primary" onclick="dispatchIssuedUnits('${r.request_id}')">Issue & Dispatch</button>
            ` : ''}
          ` : ''}
          ${r.status === 'Fulfilled' ? `<span style="color:#16a34a; font-weight:600;">Fulfilled</span>` : ''}
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {}
}

function openNewRequestModal() {
  document.getElementById("reqHospital").value = "City Care Hospital";
  document.getElementById("reqDoctor").value = "Dr. S. Patil";
  document.getElementById("reqPatient").value = "";
  document.getElementById("reqGroup").value = "O+";
  document.getElementById("reqComp").value = "Whole Blood";
  document.getElementById("reqQuantity").value = "1";
  document.getElementById("reqUrgency").value = "Normal";
  openModal("newRequestModal");
}

async function submitNewRequest() {
  const hospital_name = document.getElementById("reqHospital").value.trim();
  const requester_name = document.getElementById("reqDoctor").value.trim();
  const patient_name = document.getElementById("reqPatient").value.trim();
  const patient_blood_group = document.getElementById("reqGroup").value;
  const component_type = document.getElementById("reqComp").value;
  const quantity = parseInt(document.getElementById("reqQuantity").value, 10);
  const urgency = document.getElementById("reqUrgency").value;
  const required_date = new Date().toISOString().split("T")[0];

  if (!hospital_name || !requester_name || !patient_name) {
    showToast("Hospital, requester, and patient names are required.", "warning");
    return;
  }

  try {
    const res = await apiCall("/api/requests", "POST", {
      hospital_name, requester_name, patient_name, patient_blood_group,
      component_type, quantity, urgency, required_date
    });
    showToast(`Request submitted! Assigned ID: ${res.request_id}`, "success");
    closeModal("newRequestModal");
    loadRequests();
    loadNotifications();
  } catch (err) {}
}

function openDecisionModal(requestId) {
  document.getElementById("decisionModalReqId").value = requestId;
  document.getElementById("decisionModalTitle").innerText = `Decide Request: ${requestId}`;
  document.getElementById("decisionChoice").value = "Approved";
  document.getElementById("decisionReason").value = "Verified medical indication and urgency.";
  openModal("requestDecisionModal");
}

async function submitRequestDecision() {
  const requestId = document.getElementById("decisionModalReqId").value;
  const decision = document.getElementById("decisionChoice").value;
  const reason = document.getElementById("decisionReason").value.trim();

  if (!reason) {
    showToast("Decision reason is mandatory.", "warning");
    return;
  }

  try {
    await apiCall(`/api/requests/${requestId}/decision`, "POST", { decision, reason });
    showToast(`Request ${requestId} decision recorded: ${decision}`, "success");
    closeModal("requestDecisionModal");
    loadRequests();
  } catch (err) {}
}

// ===================== FEFO ALLOCATION =====================
async function openFefoModal(requestId) {
  try {
    const res = await apiCall(`/api/allocations/preview/${requestId}`);
    document.getElementById("fefoModalReqId").value = requestId;
    document.getElementById("fefoModalTitle").innerText = `FEFO Allocation Engine: ${requestId}`;
    const tbody = document.getElementById("fefoCandidatesTableBody");
    tbody.innerHTML = "";

    if (res.candidates.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:1.5rem; color:#dc2626; font-weight:600;">No available compatible units in stock for this request!</td></tr>`;
      document.getElementById("fefoConfirmBtn").disabled = true;
    } else {
      document.getElementById("fefoConfirmBtn").disabled = false;
      res.candidates.forEach((c, idx) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><span class="badge ${idx === 0 ? 'badge-primary' : 'badge-neutral'}">${idx === 0 ? '1st (FEFO)' : idx + 1}</span></td>
          <td><strong>${c.unit_id}</strong></td>
          <td><span class="badge badge-danger">${c.blood_group}</span> ${c.is_exact_match ? '<small style="color:#16a34a;">(Exact)</small>' : '<small style="color:#2563eb;">(Compatible)</small>'}</td>
          <td>${c.component_type}</td>
          <td>${c.expiry_date} <small style="color:#d97706;">(${c.days_until_expiry}d left)</small></td>
          <td>${c.storage_location}</td>
        `;
        tbody.appendChild(tr);
      });
    }
    openModal("fefoAllocationModal");
  } catch (err) {}
}

async function confirmFefoAllocation() {
  const requestId = document.getElementById("fefoModalReqId").value;
  try {
    const res = await apiCall("/api/allocations/allocate", "POST", { request_id: requestId });
    showToast(res.message, "success");
    closeModal("fefoAllocationModal");
    loadRequests();
    loadDashboard();
  } catch (err) {}
}

async function dispatchIssuedUnits(requestId) {
  if (!confirm(`Confirm dispatch of blood units for request ${requestId}? This will atomically mark units as Issued.`)) return;

  try {
    const res = await apiCall("/api/issues", "POST", { request_id: requestId });
    showToast(res.message, "success");
    loadRequests();
    loadDashboard();
    // Open printable certificate for first issued unit
    if (res.issued_records && res.issued_records.length > 0) {
      openCertificateModal(res.issued_records[0].issue_id);
    }
  } catch (err) {}
}

// ===================== ISSUES & DISPATCH =====================
async function loadIssues() {
  const q = document.getElementById("issueSearch").value;
  let url = "/api/issues?";
  if (q) url += `search=${encodeURIComponent(q)}&`;

  try {
    const issues = await apiCall(url);
    const tbody = document.getElementById("issuesTableBody");
    tbody.innerHTML = "";

    if (issues.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2rem; color:#64748b;">No blood issues recorded yet.</td></tr>`;
      return;
    }

    issues.forEach((i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${i.issue_id}</strong></td>
        <td>${i.request_id}</td>
        <td><span class="badge badge-primary">${i.unit_id}</span></td>
        <td>${i.hospital_name} (Patient: ${i.patient_name})</td>
        <td><span class="badge badge-danger">${i.blood_group}</span> ${i.component_type}</td>
        <td>${i.issue_timestamp}</td>
        <td>
          <button class="btn btn-sm btn-outline" onclick="openCertificateModal('${i.issue_id}')">View Slip</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {}
}

async function openCertificateModal(issueId) {
  try {
    const c = await apiCall(`/api/issues/${issueId}/certificate`);
    document.getElementById("certIssueId").innerText = c.issue_id;
    document.getElementById("certTimestamp").innerText = c.issue_timestamp;
    document.getElementById("certHospital").innerText = c.hospital_name;
    document.getElementById("certPatient").innerText = `${c.patient_name} (${c.patient_blood_group})`;
    document.getElementById("certUnitId").innerText = c.unit_id;
    document.getElementById("certBloodGroup").innerText = `${c.blood_group} - ${c.component_type}`;
    document.getElementById("certVolume").innerText = `${c.volume_ml} mL`;
    document.getElementById("certExpiry").innerText = c.expiry_date;
    document.getElementById("certStaff").innerText = c.issuing_staff;
    document.getElementById("certNotes").innerText = c.verification_notes || "Identity and compatibility verified.";

    openModal("issueCertificateModal");
  } catch (err) {}
}

// ===================== REPORTS =====================
async function loadReportsView() {
  const repType = document.getElementById("reportTypeSelect").value;
  try {
    let data;
    if (repType === "inventory") data = await apiCall("/api/reports/inventory");
    else if (repType === "donations") data = await apiCall("/api/reports/donations");
    else if (repType === "issues") data = await apiCall("/api/reports/issues");
    else if (repType === "discards_expiries") data = await apiCall("/api/reports/discards-expiries");

    renderReportTable(repType, data);
  } catch (err) {}
}

function renderReportTable(type, data) {
  const thead = document.getElementById("reportTableHead");
  const tbody = document.getElementById("reportTableBody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  if (!data || data.length === 0) {
    tbody.innerHTML = `<tr><td style="text-align:center; padding:2rem; color:#64748b;">No report data available for selected category.</td></tr>`;
    return;
  }

  const keys = Object.keys(data[0]);
  const trHead = document.createElement("tr");
  keys.forEach((k) => {
    const th = document.createElement("th");
    th.innerText = k.replace(/_/g, " ").toUpperCase();
    trHead.appendChild(th);
  });
  thead.appendChild(trHead);

  data.forEach((row) => {
    const tr = document.createElement("tr");
    keys.forEach((k) => {
      const td = document.createElement("td");
      td.innerText = row[k] !== null ? row[k] : "";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function downloadCurrentReportCsv() {
  const repType = document.getElementById("reportTypeSelect").value;
  window.open(`/api/reports/export-csv?report_type=${repType}`, "_blank");
}

// ===================== NOTIFICATIONS =====================
async function loadNotifications() {
  try {
    const alerts = await apiCall("/api/notifications");
    const unread = alerts.filter((a) => a.is_read === 0);
    document.getElementById("notifCount").innerText = unread.length;

    const list = document.getElementById("notificationsList");
    if (list) {
      list.innerHTML = "";
      if (alerts.length === 0) {
        list.innerHTML = `<p style="color:#64748b; padding:1rem; text-align:center;">No active alerts.</p>`;
      } else {
        alerts.forEach((a) => {
          const item = document.createElement("div");
          item.style.padding = "0.75rem";
          item.style.borderBottom = "1px solid #e2e8f0";
          item.style.background = a.is_read ? "#fff" : "#fef3c7";
          item.innerHTML = `
            <div style="display:flex; justify-content:space-between;">
              <span class="badge ${a.severity === 'Critical' ? 'badge-danger' : 'badge-warning'}">${a.alert_type}</span>
              <small style="color:#64748b;">${a.created_at}</small>
            </div>
            <p style="font-size:0.85rem; margin-top:0.3rem;">${a.message}</p>
          `;
          list.appendChild(item);
        });
      }
    }
  } catch (err) {}
}

async function markAllAlertsRead() {
  try {
    await apiCall("/api/notifications/read-all", "POST");
    loadNotifications();
  } catch (err) {}
}

function toggleNotifDrawer() {
  const drawer = document.getElementById("notifDrawer");
  drawer.classList.toggle("open");
  loadNotifications();
}

// ===================== ADMIN & AUDIT =====================
async function loadAdminUsers() {
  try {
    const users = await apiCall("/api/admin/users");
    const tbody = document.getElementById("adminUsersTableBody");
    tbody.innerHTML = "";
    users.forEach((u) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>#${u.id}</strong></td>
        <td>${u.username}</td>
        <td>${u.full_name}</td>
        <td>${u.email}</td>
        <td><span class="badge badge-info">${u.role.toUpperCase()}</span></td>
        <td><span class="badge ${u.status === 'active' ? 'badge-success' : 'badge-danger'}">${u.status}</span></td>
        <td>
          <button class="btn btn-sm btn-outline" onclick="toggleUserStatus(${u.id}, '${u.status === 'active' ? 'inactive' : 'active'}')">
            ${u.status === 'active' ? 'Deactivate' : 'Activate'}
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {}
}

async function toggleUserStatus(userId, newStatus) {
  try {
    await apiCall(`/api/admin/users/${userId}/status`, "PATCH", { status: newStatus });
    showToast(`User status updated to ${newStatus}.`, "success");
    loadAdminUsers();
  } catch (err) {}
}

function openCreateUserModal() {
  document.getElementById("newUsername").value = "";
  document.getElementById("newPassword").value = "";
  document.getElementById("newFullName").value = "";
  document.getElementById("newEmail").value = "";
  document.getElementById("newRole").value = "staff";
  openModal("createUserModal");
}

async function submitCreateUser() {
  const username = document.getElementById("newUsername").value.trim();
  const password = document.getElementById("newPassword").value;
  const full_name = document.getElementById("newFullName").value.trim();
  const email = document.getElementById("newEmail").value.trim();
  const role = document.getElementById("newRole").value;

  if (!username || !password || !full_name || !email) {
    showToast("All user fields are required.", "warning");
    return;
  }

  try {
    await apiCall("/api/admin/users", "POST", { username, password, full_name, email, role });
    showToast(`User '${username}' created with role ${role.toUpperCase()}.`, "success");
    closeModal("createUserModal");
    loadAdminUsers();
  } catch (err) {}
}

async function loadAuditLogs() {
  const actor = document.getElementById("auditFilterActor").value;
  const action = document.getElementById("auditFilterAction").value;

  let url = "/api/admin/audit-logs?";
  if (actor) url += `actor=${encodeURIComponent(actor)}&`;
  if (action) url += `action=${encodeURIComponent(action)}&`;

  try {
    const logs = await apiCall(url);
    const tbody = document.getElementById("auditLogsTableBody");
    tbody.innerHTML = "";

    logs.forEach((l) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><small style="color:#64748b;">${l.timestamp}</small></td>
        <td><strong>${l.actor_username}</strong> <span class="badge badge-neutral">${l.actor_role}</span></td>
        <td><span class="badge badge-info">${l.action}</span></td>
        <td>${l.entity_type} #${l.entity_id}</td>
        <td>${l.details || ''}</td>
        <td><small style="color:#64748b;">${l.ip_address}</small></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {}
}

async function resetDemoDatabase() {
  if (!confirm("Are you sure you want to reset all data to initial seed state?")) return;
  try {
    const res = await apiCall("/api/demo/reset", "POST");
    showToast(res.message, "success");
    loadTabContent(currentTab);
  } catch (err) {}
}

// Modal helpers
function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add("open");
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove("open");
}
