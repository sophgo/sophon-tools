package main

import (
	"testing"
)

func TestProcessArgs(t *testing.T) {
	tt := []struct {
		args []string
		want string
	}{
		{[]string{"build", "-product", "se7", "-docs-dir", "/d", "-index-dir", "/i"}, "build"},
		{[]string{"query", "-product", "se7", "-top-n", "8", "问题"}, "query"},
		{[]string{"doctor", "-product", "se7"}, "doctor"},
	}
	for _, c := range tt {
		if got := processArgsRaw(c.args); got != c.want {
			t.Errorf("args=%v got=%q want=%q", c.args, got, c.want)
		}
	}
}
