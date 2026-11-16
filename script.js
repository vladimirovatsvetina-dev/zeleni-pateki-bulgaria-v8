const form = document.getElementById("booking-form");
const result = document.getElementById("booking-result");
const tourSelect = document.getElementById("tour");
const list = document.getElementById("request-list");
const storageStatus = document.getElementById("storage-status");
const clearButton = document.getElementById("clear-requests");
const STORAGE_KEY = "zeleni-pateki-requests-v3";
let tours = [];
let requests = [];

function showMessage(message, ok = false) {
  result.className = ok ? "result success" : "result error";
  result.textContent = message;
}

function loadRequests() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const data = raw === null ? [] : JSON.parse(raw);
    if (!Array.isArray(data) || !data.every(item =>
      item && typeof item.tourName === "string" &&
      typeof item.date === "string" &&
      Number.isInteger(item.people) && item.people > 0 &&
      Number.isFinite(item.total) && item.total >= 0
    )) throw new Error("Невалиден формат на запазените заявки.");
    requests = data;
    storageStatus.textContent = "Локалните заявки са заредени.";
  } catch (error) {
    requests = [];
    storageStatus.textContent = "Запазените данни не могат да се прочетат. " +
      "Използвайте бутона за изтриване, за да ги нулирате.";
    console.error(error);
  }
}

function renderRequests() {
  list.replaceChildren();
  if (requests.length === 0) {
    const item = document.createElement("li");
    item.textContent = "Все още няма учебни заявки.";
    list.append(item);
    return;
  }
  for (const request of requests) {
    const item = document.createElement("li");
    item.textContent = `${request.tourName} | ${request.date} | ` +
      `${request.people} участници | ${request.total.toFixed(2)} лв.`;
    list.append(item);
  }
}

async function loadTours() {
  try {
    const response = await fetch("data/tours.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data) || data.length === 0 || !data.every(tour =>
      tour && typeof tour.id === "string" && tour.id.trim() &&
      typeof tour.name === "string" && tour.name.trim() &&
      Number.isFinite(tour.price) && tour.price >= 0
    ) || new Set(data.map(tour => tour.id)).size !== data.length) {
      throw new Error("Проверете имената, цените и уникалните id в JSON.");
    }
    tours = data;
    tourSelect.replaceChildren(new Option("-- Изберете --", ""));
    for (const tour of tours) {
      tourSelect.add(new Option(`${tour.name} — ${tour.price} лв.`, tour.id));
    }
    tourSelect.disabled = false;
  } catch (error) {
    showMessage("Офертите не са заредени. Проверете localhost и tours.json.");
    console.error(error);
  }
}

form.addEventListener("submit", function (event) {
  event.preventDefault();
  if (!form.checkValidity()) {
    form.reportValidity();
    return;
  }
  const name = document.getElementById("name").value.trim();
  const email = document.getElementById("email").value.trim();
  const people = Number(document.getElementById("people").value);
  const date = document.getElementById("date").value;
  const tour = tours.find(item => item.id === tourSelect.value);
  const today = new Date();
  const localToday = `${today.getFullYear()}-` +
    `${String(today.getMonth() + 1).padStart(2, "0")}-` +
    `${String(today.getDate()).padStart(2, "0")}`;
  if (!name || !email || !tour || !Number.isInteger(people) ||
      people < 1 || people > 10 || !date || date < localToday) {
    showMessage("Изберете оферта, 1–10 участници и дата от днес нататък. " +
      "Името и e-mail полето не могат да бъдат празни.");
    return;
  }
  const request = {
    tourId: tour.id,
    tourName: tour.name,
    people: people,
    date: date,
    total: tour.price * people
  };
  const updatedRequests = [...requests, request];
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updatedRequests));
    requests = updatedRequests;
    renderRequests();
    storageStatus.textContent = `Запазени учебни заявки: ${requests.length}.`;
    showMessage(`${name}, учебната заявка е запазена локално. ` +
      `Ориентировъчна стойност: ${request.total.toFixed(2)} лв. ` +
      "Няма изпратен e-mail и няма потвърдена резервация.", true);
    form.reset();
  } catch (error) {
    showMessage("Браузърът не позволи запазване. Заявката не е добавена.");
    console.error(error);
  }
});

clearButton.addEventListener("click", function () {
  if (!window.confirm("Да изтрия всички учебни заявки от този браузър?")) return;
  try {
    localStorage.removeItem(STORAGE_KEY);
    requests = [];
    renderRequests();
    storageStatus.textContent = "Всички локални учебни заявки са изтрити.";
    result.textContent = "";
    result.className = "result";
  } catch (error) {
    storageStatus.textContent = "Браузърът не позволи изтриване.";
    console.error(error);
  }
});

loadRequests();
renderRequests();
loadTours();