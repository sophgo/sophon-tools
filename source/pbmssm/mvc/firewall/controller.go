package firewall

import (
	"errors"
	"net/http"
	"strconv"

	"bmssm/pkg/firewall"
	"bmssm/pkg/response"

	"github.com/gin-gonic/gin"
)

// Controller holds a Service and exposes gin handler methods.
type Controller struct{ svc *Service }

// NewController creates a Controller with the given Service.
func NewController(svc *Service) *Controller { return &Controller{svc: svc} }

// DefaultController creates a Controller backed by the default (global-DB) Service.
func DefaultController() *Controller { return NewController(DefaultService()) }

// envFail checks the firewall environment. Returns true and writes a 503
// JSON response if the environment is unhealthy; returns false if healthy.
func envFail(c *gin.Context) bool {
	env := firewall.CheckEnvironment(firewall.DefaultRunner)
	if !env.OK {
		c.JSON(http.StatusServiceUnavailable, gin.H{"code": 1, "msg": "环境不满足", "result": gin.H{"environment": env}})
		return true
	}
	return false
}

// --- Status (no env check — returns environment data as the response) ---

// Status handles GET /firewall/status.
func (ctrl *Controller) Status(c *gin.Context) {
	env, protect, err := ctrl.svc.Status()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"environment": env, "protectPorts": protect}))
}

// --- Intents ---

// ListIntents handles GET /firewall/intent.
func (ctrl *Controller) ListIntents(c *gin.Context) {
	if envFail(c) {
		return
	}
	list, err := ctrl.svc.ListIntents()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(list))
}

// AddIntent handles POST /firewall/intent.
func (ctrl *Controller) AddIntent(c *gin.Context) {
	if envFail(c) {
		return
	}
	var req IntentRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid body"))
		return
	}
	if err := ctrl.svc.AddIntent(req); err != nil {
		if errors.Is(err, firewall.ErrInvalidInput) {
			c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
			return
		}
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "intent added"}))
}

// DeleteIntent handles DELETE /firewall/intent/:id.
func (ctrl *Controller) DeleteIntent(c *gin.Context) {
	if envFail(c) {
		return
	}
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	if err := ctrl.svc.DeleteIntent(id); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "deleted"}))
}

// Rebuild handles POST /firewall/rebuild.
func (ctrl *Controller) Rebuild(c *gin.Context) {
	if envFail(c) {
		return
	}
	if err := ctrl.svc.Rebuild(); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(gin.H{"message": "rebuild ok"}))
}
