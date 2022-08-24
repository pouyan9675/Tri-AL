var toolbarOptions = [
    ['bold', 'italic', 'underline', 'strike'],        // toggled buttons
    ['blockquote', 'code-block'],

    [{ 'header': 1 }, { 'header': 2 }],               // custom button values
    [{ 'list': 'ordered'}, { 'list': 'bullet' }],
    [{ 'script': 'sub'}, { 'script': 'super' }],      // superscript/subscript
    [{ 'indent': '-1'}, { 'indent': '+1' }],          // outdent/indent
    [{ 'direction': 'rtl' }],                         // text direction

    [{ 'size': ['small', false, 'large', 'huge'] }],  // custom dropdown
    [{ 'header': [1, 2, 3, 4, 5, 6, false] }],

    [{ 'color': [] }, { 'background': [] }],          // dropdown with defaults from theme
    [{ 'font': [] }],
    [{ 'align': [] }],

    ['clean'],                                         // remove formatting button
    ['link', 'formula', 'image', 'video', 'code-block']
    ];

    var quill = new Quill('#editor', {
    modules: {
        toolbar: toolbarOptions,
    },
    theme: 'snow'
    });

    quill.focus();


var form = document.getElementById("newsform");
form.addEventListener("submit", function(e) {
    var html = quill.container.firstChild.innerHTML;
    var text = quill.getText();
    document.getElementById('editor-holder').value = html;
    document.getElementById('text-holder').value = text;
  })
