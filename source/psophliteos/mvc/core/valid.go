package mvc

import (
	"errors"
	"fmt"
	"net/http"
	"strings"

	// "sophliteos/logger"

	"sophliteos/mvc/i18n"

	"github.com/go-playground/locales/en"
	"github.com/go-playground/locales/zh"
	ut "github.com/go-playground/universal-translator"
	"github.com/go-playground/validator/v10"
	zhtrans "github.com/go-playground/validator/v10/translations/zh"
)

func NotBlank(request *http.Request, values ...string) error {
	lang := GetLang(request)
	for i := 0; i < len(values); i = i + 2 {
		value := values[i+1]
		if len(value) <= 0 {
			return errors.New(values[i] + i18n.GetString(lang, value))
		}
	}
	return nil
}

func Valid(request *http.Request, req interface{}) error {
	en := en.New()
	zh := zh.New()
	uni := ut.New(en, zh)
	trans, _ := uni.GetTranslator(GetLang(request))
	validate := validator.New()
	zhtrans.RegisterDefaultTranslations(validate, trans)
	err := validate.Struct(req)
	if err != nil {
		errs := err.(validator.ValidationErrors)
		errText := fmt.Sprintf("参数错误！%v", removeStructName(errs.Translate(trans)))
		// logger.Error(errText)
		return errors.New(errText)
	}
	return err
}

func removeStructName(fields map[string]string) map[string]string {
	result := map[string]string{}

	for field, err := range fields {
		result[field[strings.Index(field, ".")+1:]] = err
	}
	return result
}
