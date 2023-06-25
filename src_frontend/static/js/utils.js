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

    // Fit the filename to the width of the conveted-files element
    oldString = `${element.title}`;

    // Set the innerText to the old string
    if (element.innerText != oldString) {
        element.innerText = oldString;
    }

    // Set the point to start removing characters from the string
    maxCharacters = oldString.length - 7;

    // Check whether the filename is too long
    while (element.scrollWidth > convertedFilesWidth) {
        // Truncate the filename by removing characters adding an ellipsis before the file extension
        newString = oldString.substring(0, maxCharacters) + "..." + oldString.substring(oldString.length - 4, oldString.length);

        // Set the innerText to the new string
        element.innerText = newString;

        // Decrement the point to start removing characters from the string by 1
        maxCharacters--;
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

    keyElement.innerText = key;
    valueElement.innerText = value;

    element.appendChild(keyElement);
    element.appendChild(valueElement);
}
