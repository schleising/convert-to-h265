// Variable which will contain the websocket
var ws;

// Variable which will contain the websocket url
var url;

// Variable to identify the timer in use
var timer = 0;

// Variable to identify whether the page is visible, set to true by default as the page is visible when it loads
var visible = true;

// Variable to store the conversion number
var conversionNumber = 0;

// Add a callback for state changes
document.addEventListener('readystatechange', event => {
    if (event.target.readyState === "complete") {
        console.log("Load Event")
        // Get the page URL
        url = document.URL;

        // Replace the http or https with ws or wss respectively
        if ( url.startsWith("https") ) {
            url = url.replace("https", "wss");
        } else if ( url.startsWith("http") ) {
            url = url.replace("http", "ws");
        }

        // Append the ws to the URL
        url = url + "ws";

        console.log("URL: " + url)

        // Check whether the websocket is open, if not open it
        openWebSocket();
    }
});

// Add an event listener to listen for page visibility changes
document.addEventListener("visibilitychange", event => {
    // If the page is now visible and the websocket is not open, open it
    if (document.visibilityState == "visible") {
        // Set the visible variable to true
        visible = true;

        // Clear the timer if it is set
        if (timer != 0) {
            clearTimeout(timer);
        }

        // Check whether the websocket is open, if not open it
        checkSocketAndSendMessage(event);
    }
    else {
        // Set the visible variable to false
        visible = false;

        // Clear the timer if it is set
        if (timer != 0) {
            clearTimeout(timer);
        }
    }
});

// Function to open a web socket
function openWebSocket() {
    console.log("Opening Websocket")
    // Create a new WebSocket
    ws = new WebSocket(url);

    // Setup callback for onmessage event
    ws.onmessage = event => {
        // Parse the message into a json object
        message = JSON.parse(event.data);

        switch (message.messageType) {
            case 'converting_files':
                // Get the conversion status
                conversionStatus = message.messageBody;

                // Get the progress element and clear it
                progressElement = document.getElementById("progress-details");
                progressElement.innerHTML = "";

                // Check whether conversion status is null
                if (conversionStatus == null) {
                    // Append a key value element to the progress element
                    appendKeyValueElement(progressElement, "No file being converted", "", [], []);

                    // Set the value of the file-progress element to 0
                    document.getElementById("file-progress").value = 0;
                } else {
                    // Get the number of files being converted
                    numFiles = conversionStatus.converting_files.length;

                    // Check whether the conversion number is greater than the number of files being converted
                    if (conversionNumber >= numFiles) {
                        // Set the conversion number to the number of files being converted minus 1
                        conversionNumber = numFiles - 1;

                        // If the conversion number is less than 0, set it to 0
                        if (conversionNumber < 0) {
                            conversionNumber = 0;
                        }
                    }

                    // Add a clickable element with the conversion number to the conversion-header element
                    conversionHeaderElement = document.getElementById("conversion-header");

                    // Remove all child elements from the conversion header element
                    while (conversionHeaderElement.firstChild) {
                        conversionHeaderElement.removeChild(conversionHeaderElement.firstChild);
                    }

                    // Loop through the files being converted
                    for (i = 0; i < numFiles; i++) {
                        // Create a new element
                        newElement = document.createElement("button");

                        // Set the id of the new element
                        newElement.id = "conversion-" + (i);

                        // Set the class of the new element
                        newElement.className = "conversion-button";

                        // Set the onclick function of the new element
                        newElement.onclick = function() { 
                            // Set the conversion number to the number at the end of the id
                            conversionNumber = this.id.match(/[0-9]+/g)[0];

                            // Clear the timer if it is set
                            if (timer != 0) {
                                clearTimeout(timer);
                            }

                            // Check whether the websocket is open, if not open it
                            checkSocketAndSendMessage(event);
                        };

                        // CHeck whether the backend name is null
                        if (conversionStatus.converting_files[i].backend_name == null) {
                            // Set the text of the new element
                            newElement.innerHTML = "File " + (i + 1);
                        } else {
                            // Set the text of the new element
                            newElement.innerHTML = conversionStatus.converting_files[i].backend_name;
                        }

                        // Append the new element to the conversion header element
                        conversionHeaderElement.appendChild(newElement);

                        // Check whether the conversion number is equal to the current index
                        if (conversionNumber == i) {
                            // Set the new element to be active
                            newElement.className = "conversion-button active";
                        }
                    }

                    // Only show the conversion data if numFiles is greater than 0
                    if (numFiles > 0) {
                        // Parse the time remaining which is in Python timedelta string format into a Date object 
                        time_array = conversionStatus.converting_files[conversionNumber].time_remaining.match(/[0-9]+/g);

                        // Check that the time array is not null
                        if (time_array == null) {
                            days = 0;
                            hours = 0;
                            minutes = 0;
                            seconds = 0;
                        } else if (time_array.length == 4) {
                            days = parseInt(time_array[0]);
                            hours = parseInt(time_array[1]);
                            minutes = parseInt(time_array[2]);
                            seconds = parseInt(time_array[3]);
                        } else if (time_array.length == 3) {
                            days = 0;
                            hours = parseInt(time_array[0]);
                            minutes = parseInt(time_array[1]);
                            seconds = parseInt(time_array[2]);
                        } else {
                            console.log("Unknown time array length: " + time_array.length);
                            days = 0;
                            hours = 0;
                            minutes = 0;
                            seconds = 0;
                        }

                        // Create a new Date object which is the current time plus the time remaining
                        expected_completion_time = new Date();
                        expected_completion_time.setDate(expected_completion_time.getDate() + days);
                        expected_completion_time.setHours(expected_completion_time.getHours() + hours);
                        expected_completion_time.setMinutes(expected_completion_time.getMinutes() + minutes);
                        expected_completion_time.setSeconds(expected_completion_time.getSeconds() + seconds);

                        // Format the expected completion time into a string with the format %A HH:MM
                        expected_completion_time = expected_completion_time.toLocaleString('en-GB', {weekday: 'long', hour12: false, hour: '2-digit', minute: '2-digit'});

                        // Append key / value elements to the progress-details element
                        appendKeyValueElement(progressElement, "Filename:", conversionStatus.converting_files[conversionNumber].filename, [], ["filename", "data-value-left"]);
                        appendKeyValueElement(progressElement, "Complete:", conversionStatus.converting_files[conversionNumber].progress.toFixed(2) + "%", [], ["data-value-left"]);
                        appendKeyValueElement(progressElement, "Time Since Start:", conversionStatus.converting_files[conversionNumber].time_since_start, [], ["data-value-left"]);
                        appendKeyValueElement(progressElement, "Time Remaining:", conversionStatus.converting_files[conversionNumber].time_remaining, [], ["data-value-left"]);
                        appendKeyValueElement(progressElement, "Completion Time:", expected_completion_time, [], ["data-value-left"]);

                        // Set the value of the file-progress element to the progress
                        document.getElementById("file-progress").value = conversionStatus.converting_files[conversionNumber].progress;
                    } else {
                        // Append a key value element to the progress element
                        appendKeyValueElement(progressElement, "No file being converted", "", [], []);

                        // Set the value of the file-progress element to 0
                        document.getElementById("file-progress").value = 0;
                    }
                }

                // Check whether the page is visible
                if (visible) {
                    // Clear the timer if it is set
                    if (timer != 0) {
                        clearTimeout(timer);
                    }

                    // Can call checkSocketAndSendMessage here, now the statistics message has been received and the server has responded
                    timer = setTimeout(checkSocketAndSendMessage, 1000);
                }

                break;
            case 'converted_files':
                // Get the files converted
                filesConverted = message.messageBody;

                // Check whether files converted is null
                if (filesConverted == null) {
                    document.getElementById("converted-files").innerHTML = "No files converted";
                } else {
                    // Clear the converted-files element
                    document.getElementById("converted-files").innerHTML = "";

                    // Loop through the filenames
                    for (i = 0; i < filesConverted.converted_files.length; i++) {
                        // Append a new key / value element to the converted-files element
                        appendKeyValueElement(
                            document.getElementById("converted-files"),
                            filesConverted.converted_files[i].filename,
                            filesConverted.converted_files[i].percentage_saved.toFixed(0) + "%",
                            ["filename"],
                            []
                        );
                    }
                }
                break;
            case 'statistics':
                // Get the statistics
                statistics = message.messageBody;

                // Check whether statistics is null
                if (statistics == null) {
                    // Set the innerHTML of the statistics element to "No statistics"
                    document.getElementById("statistics").innerHTML = "No statistics";
                } else {
                    // Clear the statistics element
                    document.getElementById("statistics").innerHTML = "";

                    // Loop through the statistics
                    for ([key, value] of Object.entries(statistics)) {
                        switch (key) {
                            case 'total_files':
                                key = "Total Files: ";
                                break;
                            case 'total_converted':
                                key = "Total Files Converted: ";
                                break;
                            case 'total_to_convert':
                                key = "Total Files to Convert: ";
                                break;
                            case 'gigabytes_before_conversion':
                                key = "GB Before Conversion: ";
                                value = value + " GB";
                                break;
                            case 'gigabytes_after_conversion':
                                key = "GB After Conversion: ";
                                value = value + " GB";
                                break;
                            case 'gigabytes_saved':
                                key = "GB Saved: ";
                                value = value + " GB";
                                break;
                            case 'percentage_saved':
                                key = "Percentage Saved: ";
                                value = value + "%";
                                break;
                            case 'total_conversion_time':
                                key = "Total Conversion Time: ";
                                break;
                            default:
                                console.log("Unknown key: " + key);
                        }

                        // Create the statistics element
                        appendKeyValueElement(document.getElementById("statistics"), key, value);
                    }
                }
                break;
            default:
                console.log("Unknown message type received: " + event.data.messageType);
        }

        // Get all the elements with the class "filename"
        filenameElements = document.getElementsByClassName("filename");

        // Loop through the filename elements
        for (i = 0; i < filenameElements.length; i++) {
            // Set the title of the filename element to the full filename
            filenameElements[i].title = `${filenameElements[i].innerHTML}`;

            // Trim the filename to the width of the filename element
            trimStringToElement(filenameElements[i]);
        }
    };

    // Add the event listener
    ws.addEventListener('open', (event) => {
        checkSocketAndSendMessage(event);
    });
};

function checkSocketAndSendMessage(event) {
    // Send the messsage, checking that the socket is open
    if (ws.readyState == WebSocket.OPEN) {
        // If the socket is open send the message
        sendMessage(event);
    } else if (ws.readyState != WebSocket.CONNECTING) {
        // If the socket is not open or connecting, open a new socket
        openWebSocket();
    }
};

function sendMessage(event) {
    // Create the message
    msg = {
        messageType: 'ping'
    };

    // Convert the JSON to a string and send it to the server
    ws.send(JSON.stringify(msg));
};
