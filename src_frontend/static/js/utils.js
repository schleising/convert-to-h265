// Add an event listener to listen for size changes on the window
window.addEventListener("resize", () => {
    // Get all the elements with the class "filename"
    const filenameElements = document.getElementsByClassName("filename");

    // For each element
    for (let i = 0; i < filenameElements.length; i++) {
        // Trim the string to fit into the element
        trimStringToElement(filenameElements[i]);
    }
});

// Add an event listener to listen for the document to finish loading
document.addEventListener("DOMContentLoaded", () => {
    // Get all the elements with the class "filename"
    const filenameElements = document.getElementsByClassName("filename");

    // For each element
    for (let i = 0; i < filenameElements.length; i++) {
        // Add an event listener to listen for size changes on the element
        filenameElements[i].addEventListener("resize", () => {
            // Trim the string to fit into the element
            trimStringToElement(filenameElements[i]);
        });
    }
});

// Function to trim a string to fit into an element by adding ellipsis in the middle
function trimStringToElement(element) {
    // Get the width of the converted-files element
    convertedFilesWidth = element.offsetWidth;

    // Work out the maximum number of characters that can fit in the converted-files element
    maxCharacters = Math.floor(convertedFilesWidth / 8);

    // Fit the filename to the width of the conveted-files element
    oldString = element.innerText;

    // Check whether the filename is too long
    if (oldString.length > maxCharacters) {
        // Truncate the filename by adding an ellipsis in the middle of the filename
        newString = oldString.substring(0, maxCharacters / 2 - 2) + "..." + oldString.substring(oldString.length - maxCharacters / 2 + 2, oldString.length);

        // Set the innerText to the new string
        element.innerText = newString;
    }
}

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

    keyElement.innerHTML = key;
    valueElement.innerHTML = value;

    element.appendChild(keyElement);
    element.appendChild(valueElement);
}
