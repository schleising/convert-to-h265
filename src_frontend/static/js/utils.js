function appendKeyValueElement(element, key, value, additionalKeyClass = [], additionalValueClass = []) {
    var keyElement = document.createElement("div");
    keyElement.classList.add("data-key");

    if (additionalKeyClass.length > 0) {
        keyElement.classList.add(...additionalKeyClass);
    }

    var valueElement = document.createElement("div");
    valueElement.classList.add("data-value");

    if (additionalValueClass.length > 0) {
        valueElement.classList.add(...additionalValueClass);
    }

    keyElement.innerText = key;
    valueElement.innerText = value;

    element.appendChild(keyElement);
    element.appendChild(valueElement);
}
