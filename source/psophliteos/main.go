package main

import (
	"time"

	"sophliteos/initialization"
	"sophliteos/logger"
)

func main() {
	initialization.InitBase()
	Router := initialization.Routers()
	s := initialization.InitServer(Router)

	time.Sleep(10 * time.Microsecond)

	err := s.ListenAndServe()
	if err != nil {
		logger.Error("An error occurred starting HTTP listener %v", err)
	}
}
