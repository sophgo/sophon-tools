package ws

import (
	"net/http"

	"sophliteos/logger"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{}

func SocketHandler(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		logger.Info("Error during connection upgrading: ", err)
		return
	}
	defer conn.Close()

	for {
		messageType, message, err := conn.ReadMessage()
		if err != nil {
			logger.Info("Error during message reading: ", err)
			break
		}
		logger.Info("Received: %s", message)
		err = conn.WriteMessage(messageType, message)
		if err != nil {
			logger.Info("Error during message writing: ", err)
			break
		}
	}
}
