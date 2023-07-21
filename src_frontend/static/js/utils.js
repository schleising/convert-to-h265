function appendKeyValueElement(element, key, value, additionalKeyClass = [], additionalValueClass = []) {
    // Create wrapper element
    var wrapperElement = document.createElement("div");
    wrapperElement.classList.add("key-value-wrapper");

    // Create key element
    var keyElement = document.createElement("div");
    keyElement.classList.add("data-key");

    if (additionalKeyClass.length > 0) {
        keyElement.classList.add(...additionalKeyClass);
    }

    // Create value element
    var valueElement = document.createElement("div");
    valueElement.classList.add("data-value");

    if (additionalValueClass.length > 0) {
        valueElement.classList.add(...additionalValueClass);
    }

    // Set key and value text
    keyElement.innerText = key;
    valueElement.innerText = value;

    // Append key and value elements as children of the wrapper
    wrapperElement.appendChild(keyElement);
    wrapperElement.appendChild(valueElement);

    // Append wrapper element as a child of the input element
    element.appendChild(wrapperElement);
}
