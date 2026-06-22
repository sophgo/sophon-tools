package system

import (
	"net/http"

	"sophliteos/client/ssm"
	"sophliteos/database"
	mvc "sophliteos/mvc/core"

	"github.com/gin-gonic/gin"
)

type LogApi struct{}

func (b *LogApi) AlarmLogQuery(c *gin.Context) {
	r := mvc.WrapperQuery(c.Request)
	componentType := r.Get("componentType")
	startTime := r.GetDate("startTime")
	endTime := r.GetDate("endTime")
	pageNo := r.Required().GetInt("pageNo")
	pageSize := r.Required().GetInt("pageSize")
	var alarm database.Alarm
	alarm.ComponentType = componentType
	page := database.QueryAlarms(&alarm, *pageNo, *pageSize, startTime, endTime)

	if page.Total > 0 {
		cr, _ := ssm.GetCtrlResource()
		dMap := make(map[string]string)
		dMap[cr.DeviceSn] = cr.CentralProcessingUnit.NetCard[0].IP
		for _, board := range cr.CoreComputingUnit.Board {
			if len(board.CoreSys.NetCards) > 0 {
				dMap[board.BoardSn] = board.CoreSys.NetCards[0].IP
			}
		}
		items := page.Items.([]database.Alarm)
		for i := 0; i < len(items); i++ {
			items[i].DeviceIp = dMap[items[i].CoreUnitBoardSn]
		}
		page.Items = items
	}
	c.JSON(http.StatusOK, mvc.Success(page))
}

func (b *LogApi) OptLogQuery(c *gin.Context) {

	r := mvc.WrapperQuery(c.Request)
	startTime := r.GetDate("startTime")
	endTime := r.GetDate("endTime")
	pageNo := r.Required().GetInt("pageNo")
	pageSize := r.Required().GetInt("pageSize")
	var optLog database.OptLog
	optLog.UserName = r.Get("username")
	optLog.OperationType = r.Get("operationType")
	optLog.OperationIP = r.Get("operationIp")
	optLog.OperationContent = r.Get("operationContent")

	page := database.QueryOptLogs(&optLog, *pageNo, *pageSize, startTime, endTime)
	c.JSON(http.StatusOK, mvc.Success(page))

}
