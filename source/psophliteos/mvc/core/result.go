package mvc

import (
	"sophliteos/client/ssm"
	"sophliteos/logger"
	error2 "sophliteos/mvc/error"
	"sophliteos/mvc/i18n"
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

func Handle(ssmResult ssm.SsmResult, code int) types.Result {
	var result types.Result
	if ssmResult.ErrorCode != error2.Ok {
		logger.Error("%s %s %s", i18n.GetString(i18n.Zh, code), ssmResult.ErrorCode, ssmResult.ErrorMessage)
		panic(code)
	} else {
		result.Code = ssmResult.Code
		result.Msg = ssmResult.Msg
	}
	return result
}

func HandleResult(ssmResult ssm.SsmResult, err error, code int) types.Result {
	HandleError(err, code)
	return Handle(ssmResult, code)
}
