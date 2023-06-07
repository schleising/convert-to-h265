// Variable which will contain the websocket
var ws;

// Variable which will contain the websocket url
var url;

// Variable for the periodic task
var intervalId = null;

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
            case 'converting_file':
                // Get the conversion status
                conversionStatus = message.messageBody;

                // Check whether conversion status is null
                if (conversionStatus == null) {
                    // Set the innerHTML of the filename element to "No file being converted"
                    document.getElementById("filename").innerHTML = "No file being converted";

                    // Set the value of the file-progress element to 0
                    document.getElementById("file-progress").value = 0;
                } else {
                    // Set the innerHTML of the filename element to the filename
                    document.getElementById("filename").innerHTML = "Currently Converting: " + conversionStatus.filename;

                    // Set the value of the file-progress element to the progress
                    document.getElementById("file-progress").value = conversionStatus.progress;
                }
                break;
            case 'files_to_convert':
                // Get the files to convert
                filesToConvert = message.messageBody;

                // Check whether files to convert is null
                if (filesToConvert.filenames == null) {
                    document.getElementById("files-to-convert").innerHTML = "No files to convert";
                } else {
                    // Convert the list of files to convert to a string with a new line between each file
                    filesToConvertString = filesToConvert.filenames.join("<br>");

                    // Set the innerHTML of the files-to-convert element to the string
                    document.getElementById("files-to-convert").innerHTML = filesToConvertString;
                }
                break;
            case 'converted_files':
                // Get the files converted
                filesConverted = message.messageBody;

                // Check whether files converted is null
                if (filesConverted.filenames == null) {
                    document.getElementById("converted-files").innerHTML = "No files converted";
                } else {
                    // Convert the list of files converted to a string with a new line between each file
                    filesConvertedString = filesConverted.filenames.join("<br>");

                    // Set the innerHTML of the converted-files element to the string
                    document.getElementById("converted-files").innerHTML = filesConvertedString;
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
                            default:
                                console.log("Unknown key: " + key);
                        }

                        // Create the statistics element
                        statisticsElement = createStatisticsElement(key, value);

                        // Append the statistics element to the statistics element
                        document.getElementById("statistics").appendChild(statisticsElement);
                    }
                }
                break;
            default:
                console.log("Unknown message type received: " + event.data.messageType);
        }
    };

    // Add the event listener
    ws.addEventListener('open', (event) => {
        console.log("Setting Interval")
        if (intervalId != null) {
            clearInterval(intervalId);
        }
        intervalId = setInterval(checkSocketAndSendMessage, 1000);
        checkSocketAndSendMessage();
    });
};

function checkSocketAndSendMessage(event) {
    // Send the messsage, checking that the socket is open
    // If the socket is not open, open a new one and wait for it to be ready
    if (ws.readyState != WebSocket.OPEN) {
        // Open the new socket
        openWebSocket();
    } else {
        // If the socket is already open, just send the message
        sendMessage(event);
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
