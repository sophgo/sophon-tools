package mvc

import (
	"sophliteos/logger"
	error2 "sophliteos/mvc/error"
	"sophliteos/mvc/types"
)

func Result(code int, result interface{}, msg string) types.Result {
	return types.Result{
		Code:   code,
		Msg:    msg,
		Result: result,
	}
}

func Ok() types.Result {
	return Result(error2.Ok, nil, "ok")
}
func OkWithMsg(msg string) types.Result {
	return Result(error2.Ok, nil, msg)
}

func Success(result interface{}) types.Result {
	return Result(error2.Ok, result, "ok")
}

func Error(error string) types.Result {
	return types.Result{
		Code: error2.Err,
		Msg:  error,
	}
}

func Fail(code int, msg string) types.Result {
	return Result(code, nil, msg)
}

func FailWithMsg(code int, msg string) types.Result {
	return Result(code, nil, msg)
}

func HandleError(err error, codes ...interface{}) {
	if err != nil {
		if len(codes) > 0 {
			// panic(fmt.Sprintf("%v\n%s", codes, err.Error()))
			logger.Error("%v\n%s", codes, err.Error())
		} else {
			// panic(err.Error())
		}
	}
}
