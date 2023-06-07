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
                    document.getElementById("filename").innerHTML = "No file being converted";
                    document.getElementById("file-progress").value = 0;
                } else {
                    document.getElementById("filename").innerHTML = conversionStatus.filename;
                    document.getElementById("file-progress").value = conversionStatus.progress;
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
