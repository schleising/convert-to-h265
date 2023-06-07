function createStatisticsElement(key, value) {
    statisticsElement = document.createElement("div");
    statisticsElement.classList.add("data-list");

    keyElement = document.createElement("div");
    keyElement.classList.add("data-key");

    valueElement = document.createElement("div");
    valueElement.classList.add("data-value");

    keyElement.innerHTML = key;
    valueElement.innerHTML = value;

    statisticsElement.appendChild(keyElement);
    statisticsElement.appendChild(valueElement);

    return statisticsElement;
}
