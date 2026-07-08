package alarm

import (
	"os"
	"testing"
	"time"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	pkgalarm "bmssm/pkg/alarm"
)

func setupTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dir := t.TempDir()
	dbPath := dir + "/test.db"
	db, err := gorm.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	db.AutoMigrate(&Alarm{})
	t.Cleanup(func() {
		os.Unsetenv("BMSSM_CONF")
		db.Close()
	})
	return db
}

func TestSaveAndListAlarms(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	if err := svc.SaveAlarm(Alarm{Code: pkgalarm.CodeCPURateAlarm, ComponentType: "cpu", Msg: "cpu高"}); err != nil {
		t.Fatalf("SaveAlarm: %v", err)
	}
	if err := svc.SaveAlarm(Alarm{Code: pkgalarm.CodeMemRateAlarm, ComponentType: "memory", Msg: "mem高"}); err != nil {
		t.Fatalf("SaveAlarm: %v", err)
	}
	if err := svc.SaveAlarm(Alarm{Code: pkgalarm.CodeBoardTempAlarm, ComponentType: "board", Msg: "板温高"}); err != nil {
		t.Fatalf("SaveAlarm: %v", err)
	}

	result, err := svc.ListAlarms(0, 10, ListFilters{})
	if err != nil {
		t.Fatalf("ListAlarms: %v", err)
	}
	if result.Total != 3 {
		t.Fatalf("expected total 3, got %d", result.Total)
	}
	if len(result.Items) != 3 {
		t.Fatalf("expected 3 items, got %d", len(result.Items))
	}
	// id desc 排序：最新（最后写入）的 board 温告警在前
	if result.Items[0].ComponentType != "board" {
		t.Fatalf("expected first item component=board, got %s", result.Items[0].ComponentType)
	}
}

func TestListAlarmsPagination(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	for i := 0; i < 5; i++ {
		_ = svc.SaveAlarm(Alarm{Code: pkgalarm.CodeCPURateAlarm, ComponentType: "cpu", Msg: "x"})
	}

	r, err := svc.ListAlarms(0, 2, ListFilters{})
	if err != nil {
		t.Fatalf("ListAlarms: %v", err)
	}
	if r.Total != 5 || len(r.Items) != 2 {
		t.Fatalf("expected total 5 / 2 items, got %d / %d", r.Total, len(r.Items))
	}

	r2, err := svc.ListAlarms(2, 2, ListFilters{})
	if err != nil {
		t.Fatalf("ListAlarms offset: %v", err)
	}
	if len(r2.Items) != 2 {
		t.Fatalf("expected 2 items at offset 2, got %d", len(r2.Items))
	}
}

func TestListAlarmsFilterByComponentType(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)

	_ = svc.SaveAlarm(Alarm{Code: pkgalarm.CodeCPURateAlarm, ComponentType: "cpu"})
	_ = svc.SaveAlarm(Alarm{Code: pkgalarm.CodeBoardTempAlarm, ComponentType: "board"})
	_ = svc.SaveAlarm(Alarm{Code: pkgalarm.CodeChipTempAlarm, ComponentType: "chip"})

	r, err := svc.ListAlarms(0, 10, ListFilters{ComponentType: "chip"})
	if err != nil {
		t.Fatalf("ListAlarms: %v", err)
	}
	if r.Total != 1 || r.Items[0].ComponentType != "chip" {
		t.Fatalf("expected 1 chip alarm, got total=%d", r.Total)
	}
}

func TestRecorderAdapterRecord(t *testing.T) {
	db := setupTestDB(t)
	svc := NewService(db)
	rec := NewRecorderAdapter(svc)
	// 固定时间便于断言（DateTime 解析失败时回退到 now）
	rec.now = func() time.Time { return time.Time{} }

	if err := rec.Record(pkgalarm.AlarmRec{
		DeviceSn:      "DEV",
		ComponentType: 1,
		BoardSn:       "BOARD-1",
		DateTime:      "2026-07-07 10:00:00",
		Code:          pkgalarm.CodeCPURateAlarm,
		Msg:           "cpu使用率过高,值为:99%",
	}); err != nil {
		t.Fatalf("Record: %v", err)
	}

	r, err := svc.ListAlarms(0, 10, ListFilters{})
	if err != nil {
		t.Fatalf("ListAlarms: %v", err)
	}
	if r.Total != 1 {
		t.Fatalf("expected 1 record, got %d", r.Total)
	}
	got := r.Items[0]
	if got.Code != pkgalarm.CodeCPURateAlarm {
		t.Errorf("code: %d", got.Code)
	}
	if got.ComponentType != "cpu" {
		t.Errorf("componentType: %s want cpu", got.ComponentType)
	}
	if got.CoreUnitBoardSn != "BOARD-1" {
		t.Errorf("boardSn: %s", got.CoreUnitBoardSn)
	}
	if got.Msg != "cpu使用率过高,值为:99%" {
		t.Errorf("msg: %s", got.Msg)
	}
	// DateTime 解析后年份应为 2026
	if got.CreatedAt.Year() != 2026 {
		t.Errorf("createdAt year: %d want 2026", got.CreatedAt.Year())
	}
}

func TestRecorderAdapterNilSvc(t *testing.T) {
	rec := NewRecorderAdapter(nil)
	if err := rec.Record(pkgalarm.AlarmRec{Code: pkgalarm.CodeCPURateAlarm}); err != nil {
		t.Fatalf("nil svc should not error, got %v", err)
	}
}

func TestCodeToComponentTypeAllCodes(t *testing.T) {
	cases := map[int]string{
		pkgalarm.CodeCPURateAlarm:     "cpu",
		pkgalarm.CodeCPURateRecover:   "cpu",
		pkgalarm.CodeMemRateAlarm:     "memory",
		pkgalarm.CodeMemRateRecover:   "memory",
		pkgalarm.CodeDiskRateAlarm:    "disk",
		pkgalarm.CodeDiskRateRecover:  "disk",
		pkgalarm.CodeBoardTempAlarm:   "board",
		pkgalarm.CodeBoardTempRecover: "board",
		pkgalarm.CodeChipTempAlarm:    "chip",
		pkgalarm.CodeChipTempRecover:  "chip",
		pkgalarm.CodeTPURateAlarm:     "chip",
		pkgalarm.CodeTPURateRecover:   "chip",
	}
	for code, want := range cases {
		if got := codeToComponentType(code); got != want {
			t.Errorf("code %d: got %s want %s", code, got, want)
		}
	}
}
