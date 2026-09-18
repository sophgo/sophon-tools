module sewriter

go 1.20

require (
	github.com/bodgit/sevenzip v1.6.0
	github.com/diskfs/go-diskfs v1.9.4
	github.com/klauspost/compress v1.17.9
	github.com/lxn/walk v0.0.0-20210112085537-c389da54e794
	github.com/lxn/win v0.0.0-20210218163916-a377121e959e
	github.com/nwaples/rardecode/v2 v2.0.1
	github.com/ulikunitz/xz v0.5.12
	golang.org/x/sys v0.30.0
	golang.org/x/text v0.22.0
)

require (
	github.com/andybalholm/brotli v1.1.1 // indirect
	github.com/bodgit/plumbing v1.3.0 // indirect
	github.com/bodgit/windows v1.0.1 // indirect
	github.com/djherbis/times v1.6.0 // indirect
	github.com/google/uuid v1.6.0 // indirect
	github.com/hashicorp/errwrap v1.0.0 // indirect
	github.com/hashicorp/go-multierror v1.1.1 // indirect
	github.com/hashicorp/golang-lru/v2 v2.0.7 // indirect
	github.com/pierrec/lz4/v4 v4.1.21 // indirect
	github.com/pkg/xattr v0.4.12 // indirect
	github.com/sirupsen/logrus v1.9.4 // indirect
	go4.org v0.0.0-20200411211856-f5505b9728dd // indirect
	gopkg.in/Knetic/govaluate.v3 v3.0.0 // indirect
)

replace github.com/diskfs/go-diskfs => ./third_party/go-diskfs
